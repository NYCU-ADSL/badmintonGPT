"""Per-account quotas / metering / ownership. [badmintonGPT fork]"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot import accounts
from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.providers.base import LLMProvider, LLMResponse


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_ACCOUNTS", "1")
    monkeypatch.setenv("NANOBOT_ACCOUNTS_WHITELIST", "boss@lab.org, @staff.org")
    monkeypatch.delenv("NANOBOT_ACCOUNTS_QUOTA_USD", raising=False)
    monkeypatch.delenv("NANOBOT_ACCOUNTS_PRICES", raising=False)
    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUD", raising=False)
    led = accounts.Ledger(tmp_path / "accounts.db")
    accounts.set_ledger_for_tests(led)
    yield led
    accounts.set_ledger_for_tests(None)
    led.close()


def _bind(email: str | None, session_key: str = "websocket:c1"):
    meta = {accounts.ACCOUNT_METADATA_KEY: email} if email else {}
    return bind_request_context(
        RequestContext(channel="websocket", chat_id="c1", session_key=session_key, metadata=meta)
    )


def test_whitelist_exact_and_domain(ledger):
    assert accounts.is_whitelisted("boss@lab.org")
    assert accounts.is_whitelisted("BOSS@lab.org".lower())
    assert accounts.is_whitelisted("anyone@staff.org")
    assert not accounts.is_whitelisted("anyone@lab.org")
    assert not accounts.is_whitelisted("x@evilstaff.org.example")


def test_identity_from_cloudflare_header(ledger):
    acct = accounts.account_from_headers({"Cf-Access-Authenticated-User-Email": " Boss@Lab.org "})
    assert acct == accounts.Account("boss@lab.org", True)
    assert accounts.account_from_headers({}) is None
    local = accounts.account_from_headers({}, is_local=True)
    assert local is not None and local.whitelisted


def test_jwt_mode_ignores_plain_email_header(ledger, monkeypatch):
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "team.cloudflareaccess.com")
    monkeypatch.setenv("CF_ACCESS_AUD", "aud")
    acct = accounts.account_from_headers({"Cf-Access-Authenticated-User-Email": "boss@lab.org"})
    assert acct is None


def test_pricing_prefix_cached_and_fallback(ledger, monkeypatch):
    usage = {"prompt_tokens": 1_000_000, "cached_tokens": 400_000, "completion_tokens": 100_000}
    # gpt-5.5: 0.6M * 5 + 0.4M * 0.5 + 0.1M * 30
    assert accounts.llm_cost_usd("gpt-5.5", usage) == pytest.approx(3.0 + 0.2 + 3.0)
    assert accounts.llm_cost_usd("openai/gpt-5.5-2026-01-01", usage) == pytest.approx(6.2)
    # unknown models are billed at the expensive fallback, never free
    assert accounts.llm_cost_usd("mystery", usage) == pytest.approx(6.2)
    monkeypatch.setenv(
        "NANOBOT_ACCOUNTS_PRICES", json.dumps({"mystery": {"input": 1, "output": 2}})
    )
    # cached_input defaults to the input price when omitted
    assert accounts.llm_cost_usd("mystery", usage) == pytest.approx(1.0 + 0.2)


def test_pricing_long_context_tier(ledger, monkeypatch):
    # gpt-6-luna: 0.10 / 0.01 cached / 0.50; all three double once input exceeds 272k tokens
    short = {"prompt_tokens": 272_000, "cached_tokens": 72_000, "completion_tokens": 100_000}
    # 0.2M * 0.10 + 0.072M * 0.01 + 0.1M * 0.50
    assert accounts.llm_cost_usd("gpt-6-luna", short) == pytest.approx(0.02 + 0.00072 + 0.05)
    long = {"prompt_tokens": 400_000, "cached_tokens": 100_000, "completion_tokens": 100_000}
    # 2 * (0.3M * 0.10 + 0.1M * 0.01 + 0.1M * 0.50)
    assert accounts.llm_cost_usd("openai/gpt-6-luna", long) == pytest.approx(2 * (0.03 + 0.001 + 0.05))
    # models without a tier are unaffected
    assert accounts.llm_cost_usd("gpt-5.5", long) == pytest.approx(1.5 + 0.05 + 3.0)
    monkeypatch.setenv("NANOBOT_ACCOUNTS_PRICES", json.dumps({"gpt-5.5": {
        "input": 5, "cached_input": 0.5, "output": 30,
        "long_context_threshold": 272_000, "long_context_multiplier": 2,
    }}))
    assert accounts.llm_cost_usd("gpt-5.5", long) == pytest.approx(2 * (1.5 + 0.05 + 3.0))


def test_quota_lifetime_and_override(ledger):
    user = accounts.account_for_email("student@uni.edu")
    status = accounts.quota_status(user)
    assert status["quota_usd"] == 3.0 and status["remaining_usd"] == 3.0
    assert not status["exhausted"]
    ledger.record_llm(email=user.email, session_key=None, model="gpt-5.5", usage={}, cost_usd=2.5)
    ledger.record_job(
        server="reels", job_id="j1", email=user.email, session_key=None,
        tool="get_reel_result", cost_usd=0.6, detail=None,
    )
    status = accounts.quota_status(user)
    assert status["spent_usd"] == pytest.approx(3.1)
    assert status["remaining_usd"] == 0 and status["exhausted"]
    ledger.set_quota_override(user.email, 10.0)
    assert not accounts.quota_status(user)["exhausted"]

    boss = accounts.account_for_email("boss@lab.org")
    ledger.record_llm(email=boss.email, session_key=None, model="m", usage={}, cost_usd=99)
    assert accounts.quota_status(boss)["unlimited"]
    assert not accounts.quota_status(boss)["exhausted"]


def test_job_costs_upsert_monotonic(ledger):
    for cost in (0.01, 0.05, 0.03):
        ledger.record_job(
            server="reels", job_id="j1", email="a@b.c", session_key=None,
            tool="get_reel_status", cost_usd=cost, detail={"cost_usd": cost},
        )
    assert ledger.spent_usd("a@b.c") == pytest.approx(0.05)


def test_record_mcp_result_charges_session_owner(ledger):
    ledger.claim("websocket:c1", "student@uni.edu")
    token = _bind(None)  # cron-style turn: no account metadata, falls back to the owner
    try:
        payload = {"job_id": "r-1", "state": "running", "usage": {"cost_usd": 0.02}}
        accounts.record_mcp_result("badminton-reels", "get_reel_status", json.dumps(payload))
        payload["usage"]["cost_usd"] = 0.03
        accounts.record_mcp_result("badminton-reels", "get_reel_result", "", structured=payload)
        accounts.record_mcp_result("badminton-reels", "get_reel_result", "not json")
    finally:
        reset_request_context(token)
    assert ledger.spent_usd("student@uni.edu") == pytest.approx(0.03)


class _FakeProvider(LLMProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        return LLMResponse(
            content="hi", usage={"prompt_tokens": 1000, "completion_tokens": 100}
        )

    def get_default_model(self) -> str:
        return "gpt-5.5"


@pytest.mark.asyncio
async def test_provider_meters_and_refuses_when_exhausted(ledger, monkeypatch):
    monkeypatch.setenv("NANOBOT_ACCOUNTS_QUOTA_USD", "0.01")
    provider = _FakeProvider()
    token = _bind("student@uni.edu")
    try:
        first = await provider.chat_with_retry(messages=[{"role": "user", "content": "x"}])
        assert first.content == "hi"
        # 1000 * 5/1M + 100 * 30/1M = 0.008
        assert ledger.spent_usd("student@uni.edu") == pytest.approx(0.008)
        await provider.chat_with_retry(messages=[{"role": "user", "content": "x"}])
        refused = await provider.chat_with_retry(messages=[{"role": "user", "content": "x"}])
    finally:
        reset_request_context(token)
    assert provider.calls == 2
    assert refused.finish_reason == "error"
    assert "Usage limit reached" in (refused.content or "")
    assert not LLMProvider.is_arrearage_response(refused)


@pytest.mark.asyncio
async def test_provider_unattributed_calls_are_free_and_unblocked(ledger, monkeypatch):
    monkeypatch.setenv("NANOBOT_ACCOUNTS_QUOTA_USD", "0")
    provider = _FakeProvider()
    resp = await provider.chat_with_retry(messages=[{"role": "user", "content": "x"}])
    assert resp.content == "hi"


def test_invite_migration_keeps_existing_accounts(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE users (email TEXT PRIMARY KEY, first_seen REAL NOT NULL, "
        "last_seen REAL NOT NULL, quota_override_usd REAL)"
    )
    db.execute("INSERT INTO users VALUES ('early@uni.edu', 1, 2, NULL)")
    db.commit()
    db.close()
    led = accounts.Ledger(path)
    try:
        assert led.is_activated("early@uni.edu")
        led.touch_user("late@uni.edu")
        assert not led.is_activated("late@uni.edu")
    finally:
        led.close()
    led = accounts.Ledger(path)  # the migration runs once: reopening activates nobody new
    try:
        assert not led.is_activated("late@uni.edu")
    finally:
        led.close()


def test_invite_redeem_caps_and_cooldown(ledger):
    assert ledger.create_invite(" ＡＢＣ 1 ") == "abc1"
    ledger.create_invite("two", max_uses=1)
    now = 1000.0

    assert ledger.redeem_invite("a@uni.edu", "nope", now=now) == {
        "ok": False, "reason": "invalid", "retry_after_s": 0,
    }
    assert ledger.redeem_invite("a@uni.edu", "nope", now=now)["retry_after_s"] == 0
    third = ledger.redeem_invite("a@uni.edu", "nope", now=now)
    assert third["reason"] == "invalid" and third["retry_after_s"] == 30
    assert ledger.redeem_invite("a@uni.edu", "abc1", now=now + 10)["reason"] == "cooldown"
    assert ledger.redeem_invite("a@uni.edu", "a b c １", now=now + 30)["ok"] is True
    assert ledger.is_activated("a@uni.edu")
    assert ledger.redeem_invite("a@uni.edu", "anything", now=now + 31)["reason"] == "already_active"

    assert ledger.redeem_invite("b@uni.edu", "TWO", now=now)["ok"] is True
    assert ledger.redeem_invite("c@uni.edu", "two", now=now) == {
        "ok": False, "reason": "full", "retry_after_s": 0,
    }
    assert ledger.disable_invite("abc1")
    assert ledger.redeem_invite("c@uni.edu", "abc1", now=now)["reason"] == "invalid"
    assert {r["code"]: (r["uses"], r["max_uses"], r["disabled"]) for r in ledger.list_invites()} == {
        "abc1": (1, None, True), "two": (1, 1, False),
    }
    with pytest.raises(ValueError):
        ledger.create_invite("  ")


def test_invite_gate_refuses_llm_until_redeemed(ledger, monkeypatch):
    student = accounts.account_for_email("student@uni.edu")
    assert accounts.is_activated(student)  # off by default
    monkeypatch.setenv("NANOBOT_ACCOUNTS_INVITE_REQUIRED", "1")
    assert not accounts.is_activated(student)
    assert accounts.quota_status(student)["invite_required"] is True
    assert accounts.is_activated(accounts.account_for_email("boss@lab.org"))
    token = _bind("student@uni.edu")
    try:
        assert "Invite code required" in (accounts.llm_call_refusal() or "")
        assert (accounts.mcp_call_refusal() or "").startswith("Error: Invite code required")
        ledger.activate("student@uni.edu")
        assert accounts.llm_call_refusal() is None
    finally:
        reset_request_context(token)


def test_invite_cli(ledger, monkeypatch, capsys):
    monkeypatch.setenv("NANOBOT_ACCOUNTS_INVITE_REQUIRED", "1")
    assert accounts._cli(["invite", "create", "Open Day", "--max-uses", "5"]) == 0
    assert accounts._cli(["invite", "list"]) == 0
    out = capsys.readouterr().out
    assert "openday" in out and "5" in out and "active" in out
    ledger.touch_user("new@uni.edu")
    assert accounts._cli(["list"]) == 0
    assert "NO INVITE" in capsys.readouterr().out
    assert accounts._cli(["activate", "new@uni.edu"]) == 0
    assert ledger.is_activated("new@uni.edu")
    assert accounts._cli(["invite", "disable", "open day"]) == 0
    assert ledger.list_invites()[0]["disabled"] is True


def test_private_paths(ledger, tmp_path):
    ws = tmp_path / "workspace"
    me = "student@uni.edu"
    own = ws / "projects" / accounts.account_slug(me) / "p1" / "a.txt"
    other = ws / "projects" / accounts.account_slug("x@y.z") / "p1" / "a.txt"
    token = _bind(me)
    try:
        v = accounts.private_path_violation
        assert v(ws / "sessions" / "websocket_x.jsonl", ws, write=False)
        assert v(ws / "memory" / "history.jsonl", ws, write=False)
        assert v(ws / "memory" / "MEMORY.md", ws, write=False) is None
        assert v(ws / "memory" / "MEMORY.md", ws, write=True)
        assert v(ws / "SOUL.md", ws, write=True)
        assert v(ws / "skills" / "x" / "SKILL.md", ws, write=False) is None
        assert v(own, ws, write=True) is None
        assert v(other, ws, write=False)
        assert v(ws / "notes.txt", ws, write=True) is None
        assert v(Path("/elsewhere/file"), ws, write=True) is None
    finally:
        reset_request_context(token)


def test_project_root_is_per_account(ledger, tmp_path):
    ws = tmp_path / "workspace"
    assert accounts.webui_project_root(ws) == (ws / "projects").resolve()
    token = accounts.bind_webui_account(accounts.account_for_email("student@uni.edu"))
    try:
        root = accounts.webui_project_root(ws)
    finally:
        accounts.reset_webui_account(token)
    assert root.parent == (ws / "projects").resolve()
    assert root.name == accounts.account_slug("student@uni.edu")


def test_disabled_is_inert(tmp_path, monkeypatch):
    monkeypatch.delenv("NANOBOT_ACCOUNTS", raising=False)
    assert accounts.current_account_email() is None
    assert accounts.private_path_violation(tmp_path / "sessions" / "x", tmp_path, write=False) is None
    accounts.record_llm_usage("gpt-5.5", {"prompt_tokens": 1})  # no ledger touched
