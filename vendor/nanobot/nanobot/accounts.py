"""Per-user accounts, usage metering and quotas for a proxy-authenticated WebUI.

[badmintonGPT fork] Opt-in with ``NANOBOT_ACCOUNTS=1``. The WebUI sits behind Cloudflare Access,
which authenticates every request and forwards the user's identity. With accounts enabled:

* every WebUI request is mapped to an :class:`Account` (the Access user's e-mail);
* each ``websocket:<chat_id>`` session is owned by the account that created it, and only that
  account can list / read / attach to / delete it;
* every LLM call and every billable MCP job is metered in a SQLite ledger and charged to the
  owner of the session it ran for;
* accounts on the whitelist are unlimited; everyone else gets a lifetime quota
  (``NANOBOT_ACCOUNTS_QUOTA_USD``, default 3.00) and is refused new turns / LLM calls / tool
  calls once it is spent.

Environment:

``NANOBOT_ACCOUNTS``                 ``1`` enables everything here (unset → stock behaviour).
``NANOBOT_ACCOUNTS_WHITELIST``       comma/space separated e-mails; ``@example.org`` entries match
                                     a whole domain. Whitelisted = unlimited + may use Settings.
``NANOBOT_ACCOUNTS_QUOTA_USD``       lifetime quota for non-whitelisted accounts (default 3.00).
``NANOBOT_ACCOUNTS_PRICES``          JSON ``{"<model prefix>": {"input": $/1M, "cached_input": $/1M,
                                     "output": $/1M}}`` merged over the built-in table; key ``"*"``
                                     is the fallback for unknown models.
``NANOBOT_ACCOUNTS_LEGACY_OWNER``    e-mail that adopts sessions created before accounts existed.
``NANOBOT_ACCOUNTS_LOCAL_USER``      identity for header-less loopback requests (host/dev mode),
                                     default ``local@localhost`` (whitelisted).
``CF_ACCESS_TEAM_DOMAIN`` + ``CF_ACCESS_AUD``
                                     when both are set the ``Cf-Access-Jwt-Assertion`` header is
                                     verified (RS256 against the team's certs) instead of trusting
                                     the plain ``Cf-Access-Authenticated-User-Email`` header.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

ACCOUNT_METADATA_KEY = "account_email"

_TRUTHY = {"1", "true", "yes", "on"}

# USD per 1M tokens. Matched by longest model-name prefix (provider prefixes like "openai/" are
# stripped first). Override / extend with NANOBOT_ACCOUNTS_PRICES.
# Optional long-context tier: a call whose input (prompt_tokens, cached included) exceeds
# `long_context_threshold` tokens bills all three rates at `long_context_multiplier` times.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-6-luna": {
        "input": 0.10, "cached_input": 0.01, "output": 0.50,
        "long_context_threshold": 272_000, "long_context_multiplier": 2.0,
    },
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-5.1": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
}
# Unknown models are billed at the most expensive default so a misconfigured price table can
# never make usage free.
_FALLBACK_PRICE = {"input": 5.00, "cached_input": 0.50, "output": 30.00}
_PRICE_KEYS = (
    "input", "cached_input", "output", "long_context_threshold", "long_context_multiplier",
)


def accounts_enabled() -> bool:
    return os.environ.get("NANOBOT_ACCOUNTS", "").strip().lower() in _TRUTHY


def quota_usd() -> float:
    raw = os.environ.get("NANOBOT_ACCOUNTS_QUOTA_USD", "").strip()
    try:
        return max(0.0, float(raw)) if raw else 3.00
    except ValueError:
        logger.warning("invalid NANOBOT_ACCOUNTS_QUOTA_USD={!r}; using 3.00", raw)
        return 3.00


def normalize_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if not email or len(email) > 254 or "@" not in email or any(c.isspace() for c in email):
        return None
    return email


def _whitelist_entries() -> list[str]:
    raw = os.environ.get("NANOBOT_ACCOUNTS_WHITELIST", "")
    return [e.strip().lower() for e in re.split(r"[\s,;]+", raw) if e.strip()]


def is_whitelisted(email: str) -> bool:
    email = email.lower()
    for entry in _whitelist_entries():
        if entry.startswith("@"):
            if email.endswith(entry):
                return True
        elif entry == email:
            return True
    return False


def local_user() -> str:
    return normalize_email(os.environ.get("NANOBOT_ACCOUNTS_LOCAL_USER")) or "local@localhost"


@dataclass(frozen=True)
class Account:
    email: str
    whitelisted: bool

    @property
    def unlimited(self) -> bool:
        return self.whitelisted

    @property
    def can_manage_settings(self) -> bool:
        return self.whitelisted


def account_for_email(email: str) -> Account:
    whitelisted = is_whitelisted(email) or email == local_user()
    return Account(email=email, whitelisted=whitelisted)


# --- identity from proxy headers -----------------------------------------------------------


def _header(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    try:
        value = headers.get(name)
    except Exception:
        value = None
    if value is None:
        lowered = name.lower()
        try:
            for k, v in headers.items():
                if str(k).lower() == lowered:
                    value = v
                    break
        except Exception:
            return ""
    return value.strip() if isinstance(value, str) else ""


_JWKS_CLIENT: Any = None
_JWKS_LOCK = threading.Lock()


def _verify_access_jwt(token: str) -> str | None:
    """Return the verified e-mail claim of a Cloudflare Access JWT, or None."""
    team = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
    aud = os.environ.get("CF_ACCESS_AUD", "").strip()
    if not token:
        return None
    try:
        import jwt  # PyJWT (pulled in by the mcp SDK)
    except ImportError:
        logger.error("CF_ACCESS_* is set but PyJWT is not installed; rejecting request")
        return None
    if not team.startswith("http"):
        team = f"https://{team}"
    global _JWKS_CLIENT
    with _JWKS_LOCK:
        if _JWKS_CLIENT is None:
            _JWKS_CLIENT = jwt.PyJWKClient(f"{team}/cdn-cgi/access/certs", cache_keys=True)
        client = _JWKS_CLIENT
    try:
        key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=aud,
            issuer=team,
        )
    except Exception as exc:
        logger.warning("Cloudflare Access JWT rejected: {}", exc)
        return None
    return normalize_email(claims.get("email"))


def _jwt_verification_configured() -> bool:
    return bool(
        os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip()
        and os.environ.get("CF_ACCESS_AUD", "").strip()
    )


def account_from_headers(headers: Any, *, is_local: bool = False) -> Account | None:
    """Resolve the requesting account from proxy headers (None = unauthenticated)."""
    if _jwt_verification_configured():
        email = _verify_access_jwt(_header(headers, "Cf-Access-Jwt-Assertion"))
    else:
        email = normalize_email(_header(headers, "Cf-Access-Authenticated-User-Email"))
    if email is None and is_local:
        email = local_user()
    return account_for_email(email) if email else None


# --- pricing -------------------------------------------------------------------------------


def _price_table() -> dict[str, dict[str, float]]:
    table = {k: dict(v) for k, v in _DEFAULT_PRICES.items()}
    raw = os.environ.get("NANOBOT_ACCOUNTS_PRICES", "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            if isinstance(extra, dict):
                for model, price in extra.items():
                    if isinstance(price, dict):
                        table[str(model).lower()] = {
                            k: float(price[k]) for k in _PRICE_KEYS if k in price
                        }
        except (ValueError, TypeError) as exc:
            logger.warning("invalid NANOBOT_ACCOUNTS_PRICES ignored: {}", exc)
    return table


def price_for_model(model: str | None) -> dict[str, float]:
    table = _price_table()
    name = (model or "").strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[1]
    best = ""
    for key in table:
        if key != "*" and name.startswith(key) and len(key) > len(best):
            best = key
    price = dict(table.get(best) or table.get("*") or _FALLBACK_PRICE)
    price.setdefault("input", _FALLBACK_PRICE["input"])
    price.setdefault("output", _FALLBACK_PRICE["output"])
    price.setdefault("cached_input", price["input"])
    return price


def llm_cost_usd(model: str | None, usage: dict[str, Any]) -> float:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = min(int(usage.get("cached_tokens") or 0), prompt)
    price = price_for_model(model)
    threshold = price.get("long_context_threshold")
    multiplier = 1.0
    if threshold and prompt > threshold:
        multiplier = price.get("long_context_multiplier", 1.0)
    return multiplier * (
        (prompt - cached) * price["input"]
        + cached * price["cached_input"]
        + completion * price["output"]
    ) / 1_000_000


# --- ledger --------------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_owners (
    session_key TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS session_owners_email ON session_owners(email);
CREATE TABLE IF NOT EXISTS users (
    email              TEXT PRIMARY KEY,
    first_seen         REAL NOT NULL,
    last_seen          REAL NOT NULL,
    quota_override_usd REAL
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                REAL NOT NULL,
    email             TEXT NOT NULL,
    session_key       TEXT,
    model             TEXT,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    cached_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_usage_email ON llm_usage(email);
CREATE TABLE IF NOT EXISTS mcp_jobs (
    server      TEXT NOT NULL,
    job_id      TEXT NOT NULL,
    email       TEXT NOT NULL,
    session_key TEXT,
    tool        TEXT,
    cost_usd    REAL NOT NULL,
    detail      TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (server, job_id)
);
CREATE INDEX IF NOT EXISTS mcp_jobs_email ON mcp_jobs(email);
"""


class Ledger:
    """SQLite-backed ownership + usage ledger. Thread-safe; every call is a short transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._owner_cache: dict[str, str] = {}

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- users --------------------------------------------------------------

    def touch_user(self, email: str) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO users(email, first_seen, last_seen) VALUES (?, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET last_seen = excluded.last_seen",
                (email, now, now),
            )

    def quota_override(self, email: str) -> float | None:
        with self._lock:
            row = self._db.execute(
                "SELECT quota_override_usd FROM users WHERE email = ?", (email,)
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def set_quota_override(self, email: str, value: float | None) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO users(email, first_seen, last_seen, quota_override_usd) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
                "quota_override_usd = excluded.quota_override_usd",
                (email, now, now, value),
            )

    # -- session ownership --------------------------------------------------

    def owner(self, session_key: str) -> str | None:
        cached = self._owner_cache.get(session_key)
        if cached is not None:
            return cached
        with self._lock:
            row = self._db.execute(
                "SELECT email FROM session_owners WHERE session_key = ?", (session_key,)
            ).fetchone()
        if row:
            self._owner_cache[session_key] = row[0]
            return row[0]
        return None

    def claim(self, session_key: str, email: str) -> str:
        """Give *session_key* to *email* unless it is already owned; return the owner."""
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO session_owners(session_key, email, created_at) "
                "VALUES (?, ?, ?)",
                (session_key, email, time.time()),
            )
            row = self._db.execute(
                "SELECT email FROM session_owners WHERE session_key = ?", (session_key,)
            ).fetchone()
        owner = row[0]
        self._owner_cache[session_key] = owner
        return owner

    def forget(self, session_key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM session_owners WHERE session_key = ?", (session_key,))
        self._owner_cache.pop(session_key, None)

    # -- metering -----------------------------------------------------------

    def record_llm(
        self,
        *,
        email: str,
        session_key: str | None,
        model: str | None,
        usage: dict[str, Any],
        cost_usd: float,
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO llm_usage(ts, email, session_key, model, prompt_tokens, "
                "cached_tokens, completion_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    email,
                    session_key,
                    model,
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("cached_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                    float(cost_usd),
                ),
            )

    def record_job(
        self,
        *,
        server: str,
        job_id: str,
        email: str,
        session_key: str | None,
        tool: str,
        cost_usd: float,
        detail: dict[str, Any] | None,
    ) -> None:
        """Upsert a remote job's cost. Costs only ever grow (servers report running totals)."""
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO mcp_jobs(server, job_id, email, session_key, tool, cost_usd, detail, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(server, job_id) DO UPDATE SET "
                "cost_usd = MAX(mcp_jobs.cost_usd, excluded.cost_usd), "
                "detail = CASE WHEN excluded.cost_usd >= mcp_jobs.cost_usd "
                "THEN excluded.detail ELSE mcp_jobs.detail END, "
                "updated_at = excluded.updated_at",
                (
                    server,
                    job_id,
                    email,
                    session_key,
                    tool,
                    float(cost_usd),
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                    now,
                    now,
                ),
            )

    def spent_usd(self, email: str) -> float:
        with self._lock:
            llm = self._db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage WHERE email = ?", (email,)
            ).fetchone()[0]
            jobs = self._db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM mcp_jobs WHERE email = ?", (email,)
            ).fetchone()[0]
        return float(llm) + float(jobs)

    def usage_summary(self, email: str, *, recent: int = 20) -> dict[str, Any]:
        with self._lock:
            llm = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(cached_tokens), 0), "
                "COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(cost_usd), 0) "
                "FROM llm_usage WHERE email = ?",
                (email,),
            ).fetchone()
            jobs = self._db.execute(
                "SELECT server, COUNT(*), COALESCE(SUM(cost_usd), 0) FROM mcp_jobs "
                "WHERE email = ? GROUP BY server ORDER BY server",
                (email,),
            ).fetchall()
            recent_jobs = self._db.execute(
                "SELECT server, job_id, tool, cost_usd, created_at, updated_at FROM mcp_jobs "
                "WHERE email = ? ORDER BY created_at DESC LIMIT ?",
                (email, recent),
            ).fetchall()
            daily = self._db.execute(
                "SELECT day, SUM(cost) FROM ("
                "  SELECT date(ts, 'unixepoch') AS day, cost_usd AS cost FROM llm_usage "
                "  WHERE email = ? "
                "  UNION ALL "
                "  SELECT date(created_at, 'unixepoch') AS day, cost_usd AS cost FROM mcp_jobs "
                "  WHERE email = ?"
                ") GROUP BY day ORDER BY day DESC LIMIT 30",
                (email, email),
            ).fetchall()
        return {
            "llm": {
                "calls": int(llm[0]),
                "prompt_tokens": int(llm[1]),
                "cached_tokens": int(llm[2]),
                "completion_tokens": int(llm[3]),
                "cost_usd": float(llm[4]),
            },
            "jobs": [
                {"server": s, "count": int(n), "cost_usd": float(c)} for s, n, c in jobs
            ],
            "recent_jobs": [
                {
                    "server": s,
                    "job_id": j,
                    "tool": t,
                    "cost_usd": float(c),
                    "created_at": float(ca),
                    "updated_at": float(ua),
                }
                for s, j, t, c, ca, ua in recent_jobs
            ],
            "daily": [{"day": d, "cost_usd": float(c)} for d, c in daily],
        }


_LEDGER: Ledger | None = None
_LEDGER_LOCK = threading.Lock()


def ledger() -> Ledger:
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            from nanobot.config.paths import get_data_dir

            path = Path(
                os.environ.get("NANOBOT_ACCOUNTS_DB") or (get_data_dir() / "accounts.db")
            ).expanduser()
            _LEDGER = Ledger(path)
            logger.info("accounts ledger: {}", path)
        return _LEDGER


def set_ledger_for_tests(value: Ledger | None) -> None:
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = value


# --- quota ---------------------------------------------------------------------------------


def account_quota(account: Account) -> float | None:
    """The account's quota in USD, or None when unlimited."""
    if account.unlimited:
        return None
    override = ledger().quota_override(account.email)
    return override if override is not None else quota_usd()


def quota_status(account: Account) -> dict[str, Any]:
    spent = ledger().spent_usd(account.email)
    quota = account_quota(account)
    remaining = None if quota is None else max(0.0, quota - spent)
    return {
        "email": account.email,
        "whitelisted": account.whitelisted,
        "unlimited": quota is None,
        "quota_usd": quota,
        "spent_usd": round(spent, 6),
        "remaining_usd": None if remaining is None else round(remaining, 6),
        "exhausted": quota is not None and spent >= quota,
    }


def is_exhausted(email: str) -> bool:
    status = quota_status(account_for_email(email))
    return bool(status["exhausted"])


def quota_exhausted_message(email: str) -> str:
    quota = account_quota(account_for_email(email)) or 0.0
    return (
        # Wording avoids the provider-arrearage text markers in providers/base.py, which would
        # replace this with a misleading "your API key is out of credit" message.
        f"Usage limit reached: this account has used its ${quota:.2f} allowance. "
        "Contact the administrator to raise it."
    )


# --- WebUI request attribution --------------------------------------------------------------
# The websocket channel binds the requesting account around each HTTP request / WS envelope so
# helpers without an explicit account parameter (project roots, sidebar state) can scope to it.

_WEBUI_ACCOUNT: ContextVar[Account | None] = ContextVar("nanobot_webui_account", default=None)


def bind_webui_account(account: Account | None) -> Token[Account | None]:
    return _WEBUI_ACCOUNT.set(account)


def reset_webui_account(token: Token[Account | None]) -> None:
    _WEBUI_ACCOUNT.reset(token)


def current_webui_account() -> Account | None:
    return _WEBUI_ACCOUNT.get() if accounts_enabled() else None


def webui_project_root(default_workspace: Path) -> Path:
    """Where remote WebUI projects live: per-account under ``projects/`` when accounts are on."""
    root = default_workspace / "projects"
    account = current_webui_account()
    if account is not None:
        root = root / account_slug(account.email)
    return root.resolve(strict=False)


# --- agent-side attribution ----------------------------------------------------------------


def current_account_email() -> str | None:
    """The account the current agent work is billed to (None = unattributed/system)."""
    if not accounts_enabled():
        return None
    from nanobot.agent.tools.context import current_request_context

    ctx = current_request_context()
    if ctx is None:
        return None
    email = normalize_email((ctx.metadata or {}).get(ACCOUNT_METADATA_KEY))
    if email:
        return email
    if ctx.session_key:
        return ledger().owner(ctx.session_key)
    return None


def _current_session_key() -> str | None:
    from nanobot.agent.tools.context import current_request_context

    ctx = current_request_context()
    return ctx.session_key if ctx else None


def llm_call_refusal() -> str | None:
    """Message to return instead of calling the LLM when the current account is out of quota."""
    email = current_account_email()
    if email and is_exhausted(email):
        return quota_exhausted_message(email)
    return None


def record_llm_usage(model: str | None, usage: dict[str, Any] | None) -> None:
    if not usage or not accounts_enabled():
        return
    email = current_account_email()
    if not email:
        return
    try:
        cost = llm_cost_usd(model, usage)
        ledger().record_llm(
            email=email,
            session_key=_current_session_key(),
            model=model,
            usage=usage,
            cost_usd=cost,
        )
    except Exception:
        logger.exception("failed to record LLM usage for {}", email)


def mcp_call_refusal() -> str | None:
    """Refuse MCP tool calls (e.g. starting a paid reel render) once the quota is spent."""
    email = current_account_email()
    if email and is_exhausted(email):
        return f"Error: {quota_exhausted_message(email)}"
    return None


def _find_job_usage(obj: Any, depth: int = 0) -> tuple[str, float, dict[str, Any]] | None:
    if depth > 4:
        return None
    if isinstance(obj, dict):
        usage = obj.get("usage")
        job_id = obj.get("job_id")
        if isinstance(usage, dict) and isinstance(job_id, str) and job_id:
            cost = usage.get("cost_usd")
            if isinstance(cost, (int, float)) and cost >= 0:
                return job_id, float(cost), usage
        for value in obj.values():
            found = _find_job_usage(value, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj[:20]:
            found = _find_job_usage(value, depth + 1)
            if found:
                return found
    return None


def record_mcp_result(
    server: str,
    tool: str,
    text: str,
    *,
    structured: Any = None,
) -> None:
    """Charge a remote job's self-reported cost (``{"job_id", "usage": {"cost_usd"}}``)."""
    if not accounts_enabled():
        return
    payload: Any = structured if isinstance(structured, dict) else None
    if payload is None:
        if not text or '"cost_usd"' not in text:
            return
        try:
            payload = json.loads(text)
        except ValueError:
            return
    email = current_account_email()
    if not email:
        return
    found = _find_job_usage(payload)
    if not found:
        return
    job_id, cost, usage = found
    try:
        ledger().record_job(
            server=server,
            job_id=job_id,
            email=email,
            session_key=_current_session_key(),
            tool=tool,
            cost_usd=cost,
            detail=usage,
        )
    except Exception:
        logger.exception("failed to record MCP job usage {}:{}", server, job_id)


# --- private workspace paths ---------------------------------------------------------------


def shared_memory_disabled() -> bool:
    return os.environ.get("NANOBOT_DISABLE_SHARED_MEMORY", "").strip().lower() in _TRUTHY


def account_slug(email: str) -> str:
    """Stable, filesystem-safe directory name for an account."""
    import hashlib

    local = re.sub(r"[^a-z0-9_-]+", "-", email.split("@", 1)[0].lower()).strip("-")[:24] or "user"
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:10]
    return f"{local}-{digest}"


# Paths (relative to the agent workspace) whose content is per-user or global agent state.
_UNREADABLE = ("sessions", "memory/history.jsonl", "memory/.cursor", "memory/.dream_cursor")
_UNWRITABLE = ("memory", "skills", "SOUL.md", "USER.md", "AGENTS.md", "HEARTBEAT.md", "TOOLS.md")


def private_path_violation(path: Path, agent_workspace: Path | None, *, write: bool) -> str | None:
    """Return a reason when the current account must not touch *path*, else None."""
    if not accounts_enabled() or agent_workspace is None:
        return None
    try:
        rel = path.resolve(strict=False).relative_to(agent_workspace.resolve(strict=False))
    except (OSError, ValueError):
        return None
    rel_s = rel.as_posix()

    def _under(prefix: str) -> bool:
        return rel_s == prefix or rel_s.startswith(prefix + "/")

    if any(_under(p) for p in _UNREADABLE):
        return "this path holds other users' conversations"
    if _under("projects") and rel_s != "projects":
        email = current_account_email()
        own = f"projects/{account_slug(email)}" if email else None
        if not own or not _under(own):
            return "this path belongs to another user's project"
    if write and any(_under(p) for p in _UNWRITABLE):
        return "shared agent configuration and memory are read-only"
    return None


# --- admin CLI -----------------------------------------------------------------------------
# docker compose exec gateway python -m nanobot.accounts list
# docker compose exec gateway python -m nanobot.accounts set-quota someone@example.org 10
# docker compose exec gateway python -m nanobot.accounts reset-quota someone@example.org


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m nanobot.accounts")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="every known account with spend and quota")
    p_set = sub.add_parser("set-quota", help="give one account its own lifetime quota (USD)")
    p_set.add_argument("email")
    p_set.add_argument("usd", type=float)
    p_reset = sub.add_parser("reset-quota", help="drop an account's override (back to default)")
    p_reset.add_argument("email")
    args = parser.parse_args(argv)

    led = ledger()
    if args.cmd == "list":
        with led._lock:
            emails = [r[0] for r in led._db.execute("SELECT email FROM users ORDER BY email")]
        print(f"{'email':40} {'plan':10} {'spent':>10} {'quota':>10}")
        for email in emails:
            status = quota_status(account_for_email(email))
            quota = "-" if status["quota_usd"] is None else f"${status['quota_usd']:.2f}"
            plan = "unlimited" if status["unlimited"] else ("EXHAUSTED" if status["exhausted"] else "quota")
            print(f"{email:40} {plan:10} {'$%.4f' % status['spent_usd']:>10} {quota:>10}")
        return 0
    email = normalize_email(args.email)
    if email is None:
        parser.error(f"not an e-mail address: {args.email!r}")
    led.set_quota_override(email, args.usd if args.cmd == "set-quota" else None)
    print(json.dumps(quota_status(account_for_email(email)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
