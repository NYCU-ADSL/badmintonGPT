"""Link-only puzzle answer page: server-side check + per-account wrong-answer cooldown.

[badmintonGPT fork] Serves ``/puzzle.html`` (a static page, behind Cloudflare Access like every
path except ``/welcome.html``) through ``GET /api/puzzle`` and ``GET /api/puzzle/answer``
in ``channels/websocket.py``. The answer never reaches the browser: it lives only in the
``NANOBOT_PUZZLE_ANSWER`` env var (repo-root ``.env``) and is compared here.

After the n-th wrong answer the account must wait n/2 minutes before it may answer again
(30 s, 1 min, 1.5 min, ...). Attempts are stored per e-mail in SQLite
(``NANOBOT_PUZZLE_DB``, default ``<data dir>/puzzle.db``) so a restart does not reset them.

A correct answer is followed by a short user survey (``GET /api/puzzle/survey``, one per
account, only once solved); the page shows the stamp-collecting "done" screen only after it.
Export the answers: ``python -m nanobot.puzzle export > survey.csv``.

The "done" screen carries a QR code with the account's random ``stamp_code``. Staff (the
``NANOBOT_PUZZLE_STAFF`` list) scan it on ``/puzzle-staff.html``; ``GET /api/puzzle/staff/lookup``
returns that player's survey and counts the scans, so a second stamp for one player shows up.

Env:
``NANOBOT_PUZZLE_ANSWER``  the accepted answer; unset/empty → the page reports "not configured".
``NANOBOT_PUZZLE_STAFF``   comma/space separated staff e-mails (``@example.org`` = whole domain).
``NANOBOT_PUZZLE_DB``      optional SQLite path override.
"""

from __future__ import annotations

import csv
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from loguru import logger

# Each wrong answer adds half a minute to the wait before the next attempt.
COOLDOWN_PER_WRONG_S = 30.0
MAX_ANSWER_CHARS = 100

# Survey fields (the page's form names). Ratings are inclusive integer ranges; choices are closed
# sets. ``other_fit`` is asked (and required) only when ``tried_other`` is "yes".
SURVEY_RATINGS: dict[str, tuple[int, int]] = {
    "fit": (1, 5),         # 解謎時，回答符合需求
    "other_fit": (1, 5),   # 自己試的其他問題，回答符合需求
    "overall": (1, 5),     # 整體滿意度
    "recommend": (1, 5),   # 推薦給球友 / 隊友的可能性
}
SURVEY_CHOICES: dict[str, tuple[str, ...]] = {
    "tried_other": ("yes", "no"),
    "role": ("player", "coach", "amateur", "fan", "research", "public", "other"),
    "level": ("none", "casual", "regular", "competitive"),
}
SURVEY_TEXT_MAX_CHARS = 500  # ``suggestion``; keeps the GET URL under the 8 KiB request-line cap
SURVEY_FIELDS = (
    "fit", "tried_other", "other_fit", "overall", "recommend", "role", "level", "suggestion",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS puzzle_attempts (
    email        TEXT PRIMARY KEY,
    wrong_count  INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    solved_at    REAL
);
CREATE TABLE IF NOT EXISTS puzzle_surveys (
    email            TEXT PRIMARY KEY,
    submitted_at     REAL NOT NULL,
    answers          TEXT NOT NULL,
    stamp_code       TEXT NOT NULL UNIQUE,
    scan_count       INTEGER NOT NULL DEFAULT 0,
    first_scanned_at REAL
);
"""


def configured_answer() -> str:
    return normalize_answer(os.environ.get("NANOBOT_PUZZLE_ANSWER", ""))


def is_staff(email: str | None) -> bool:
    """Is *email* on ``NANOBOT_PUZZLE_STAFF``? Same syntax as ``NANOBOT_ACCOUNTS_WHITELIST``."""
    if not email:
        return False
    email = email.lower()
    for entry in re.split(r"[\s,;]+", os.environ.get("NANOBOT_PUZZLE_STAFF", "").lower()):
        if entry and (email == entry or (entry.startswith("@") and email.endswith(entry))):
            return True
    return False


def normalize_stamp_code(value: str) -> str:
    """Accept a bare code or the whole scanned URL (``.../puzzle-staff.html#c=<code>``)."""
    value = (value or "").strip()
    match = re.search(r"[#?&]c=([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value


def normalize_answer(value: str) -> str:
    """NFKC (full-width → half-width) and drop all whitespace, so 「謎 底」 matches 「謎底」."""
    return "".join(unicodedata.normalize("NFKC", value or "").split())


def cooldown_s(wrong_count: int) -> float:
    return wrong_count * COOLDOWN_PER_WRONG_S


def validate_survey(raw: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(answers, None)`` or ``(None, bad_field)``. Unknown keys are ignored."""
    answers: dict[str, Any] = {}
    for field, choices in SURVEY_CHOICES.items():
        value = (raw.get(field) or "").strip()
        if value not in choices:
            return None, field
        answers[field] = value
    for field, (low, high) in SURVEY_RATINGS.items():
        if field == "other_fit" and answers["tried_other"] != "yes":
            continue
        value = (raw.get(field) or "").strip()
        if not value.isdigit() or not low <= int(value) <= high:
            return None, field
        answers[field] = int(value)
    suggestion = (raw.get("suggestion") or "").strip()
    if len(suggestion) > SURVEY_TEXT_MAX_CHARS:
        return None, "suggestion"
    answers["suggestion"] = suggestion
    return answers, None


class PuzzleStore:
    """Per-account attempt state. Thread-safe; every call is one short transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring a ``puzzle_surveys`` table from before the staff QR up to date (the CREATE above
        skips an existing table): add the scan columns and give every old survey a stamp code."""
        cols = {row[1] for row in self._db.execute("PRAGMA table_info(puzzle_surveys)")}
        if "stamp_code" in cols:
            return
        self._db.execute("ALTER TABLE puzzle_surveys ADD COLUMN stamp_code TEXT")
        self._db.execute("ALTER TABLE puzzle_surveys ADD COLUMN scan_count INTEGER NOT NULL DEFAULT 0")
        self._db.execute("ALTER TABLE puzzle_surveys ADD COLUMN first_scanned_at REAL")
        for (email,) in self._db.execute("SELECT email FROM puzzle_surveys").fetchall():
            self._db.execute(
                "UPDATE puzzle_surveys SET stamp_code = ? WHERE email = ?",
                (secrets.token_urlsafe(12), email),
            )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS puzzle_surveys_stamp_code ON puzzle_surveys(stamp_code)"
        )
        logger.info("puzzle store: added stamp codes to the survey table")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _row(self, email: str) -> tuple[int, float, float | None]:
        row = self._db.execute(
            "SELECT wrong_count, locked_until, solved_at FROM puzzle_attempts WHERE email = ?",
            (email,),
        ).fetchone()
        return (int(row[0]), float(row[1]), row[2]) if row else (0, 0.0, None)

    def _survey(self, email: str) -> tuple[float | None, str | None]:
        row = self._db.execute(
            "SELECT submitted_at, stamp_code FROM puzzle_surveys WHERE email = ?", (email,)
        ).fetchone()
        return (float(row[0]), row[1]) if row else (None, None)

    def _payload(
        self, email: str, wrong: int, locked_until: float, solved_at: float | None, now: float
    ) -> dict[str, Any]:
        surveyed_at, stamp_code = self._survey(email)
        return {
            "configured": True,
            "solved": solved_at is not None,
            "wrong_count": wrong,
            "retry_after_s": 0 if solved_at is not None else max(0, round(locked_until - now)),
            "surveyed": surveyed_at is not None,
            "surveyed_at": surveyed_at,
            "stamp_code": stamp_code,
        }

    def status(self, email: str, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            wrong, locked_until, solved_at = self._row(email)
            return self._payload(email, wrong, locked_until, solved_at, now)

    def submit_survey(
        self, email: str, answers: dict[str, Any], *, now: float | None = None
    ) -> dict[str, Any]:
        """Store *answers* (already validated) once. ``ok=False, reason="unsolved"`` before solving;
        a second submission keeps the first and still reports ``ok``."""
        now = time.time() if now is None else now
        with self._lock:
            wrong, locked_until, solved_at = self._row(email)
            if solved_at is None:
                body = self._payload(email, wrong, locked_until, solved_at, now)
                return {**body, "ok": False, "reason": "unsolved"}
            self._db.execute(
                "INSERT OR IGNORE INTO puzzle_surveys(email, submitted_at, answers, stamp_code) "
                "VALUES (?, ?, ?, ?)",
                (email, now, json.dumps(answers, ensure_ascii=False), secrets.token_urlsafe(12)),
            )
            return {**self._payload(email, wrong, locked_until, solved_at, now), "ok": True}

    def scan(self, stamp_code: str, *, now: float | None = None) -> dict[str, Any] | None:
        """Staff scanned *stamp_code*: count the scan and return that player's survey, or None.
        ``scan_count`` includes this scan, so anything above 1 means the QR was shown before."""
        now = time.time() if now is None else now
        with self._lock:
            row = self._db.execute(
                "SELECT email, submitted_at, answers, scan_count, first_scanned_at "
                "FROM puzzle_surveys WHERE stamp_code = ?",
                (stamp_code,),
            ).fetchone()
            if row is None:
                return None
            email, submitted_at, answers, scans, first = row
            self._db.execute(
                "UPDATE puzzle_surveys SET scan_count = scan_count + 1, "
                "first_scanned_at = COALESCE(first_scanned_at, ?) WHERE stamp_code = ?",
                (now, stamp_code),
            )
        return {
            "email": email,
            "surveyed_at": submitted_at,
            "answers": json.loads(answers),
            "scan_count": int(scans) + 1,
            "first_scanned_at": first if first is not None else now,
        }

    def export_rows(self) -> list[dict[str, Any]]:
        """Every survey, joined with that account's puzzle attempts, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT s.email, s.submitted_at, s.answers, a.wrong_count, a.solved_at, s.scan_count "
                "FROM puzzle_surveys s LEFT JOIN puzzle_attempts a ON a.email = s.email "
                "ORDER BY s.submitted_at"
            ).fetchall()
        out = []
        for email, submitted_at, answers, wrong, solved_at, scans in rows:
            out.append({
                "email": email,
                "solved_at": solved_at,
                "wrong_count": wrong,
                "submitted_at": submitted_at,
                "scan_count": scans,
                **json.loads(answers),
            })
        return out

    def attempt(self, email: str, answer: str, expected: str, *, now: float | None = None) -> dict[str, Any]:
        """Check *answer*. Refused (``accepted=False``) while cooling down or once solved."""
        now = time.time() if now is None else now
        with self._lock:
            wrong, locked_until, solved_at = self._row(email)
            if solved_at is not None or now < locked_until:
                body = self._payload(email, wrong, locked_until, solved_at, now)
                return {**body, "accepted": False, "correct": solved_at is not None}
            correct = hmac.compare_digest(
                normalize_answer(answer).encode("utf-8"), expected.encode("utf-8")
            )
            if correct:
                solved_at = now
            else:
                wrong += 1
                locked_until = now + cooldown_s(wrong)
            self._db.execute(
                "INSERT INTO puzzle_attempts(email, wrong_count, locked_until, solved_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(email) DO UPDATE SET "
                "wrong_count = excluded.wrong_count, locked_until = excluded.locked_until, "
                "solved_at = excluded.solved_at",
                (email, wrong, locked_until, solved_at),
            )
            body = self._payload(email, wrong, locked_until, solved_at, now)
        return {**body, "accepted": True, "correct": correct}


_STORE: PuzzleStore | None = None
_STORE_LOCK = threading.Lock()


def store() -> PuzzleStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            from nanobot.config.paths import get_data_dir

            path = Path(
                os.environ.get("NANOBOT_PUZZLE_DB") or (get_data_dir() / "puzzle.db")
            ).expanduser()
            _STORE = PuzzleStore(path)
            logger.info("puzzle store: {}", path)
        return _STORE


def set_store_for_tests(value: PuzzleStore | None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = value


# docker compose exec gateway python -m nanobot.puzzle export > survey.csv


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(prog="python -m nanobot.puzzle")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export", help="every survey answer as CSV (UTF-8 with BOM, opens in Excel)")
    parser.parse_args(argv)

    def iso(ts: float | None) -> str:
        return "" if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")

    columns = ("email", "solved_at", "wrong_count", "submitted_at", "scan_count", *SURVEY_FIELDS)
    sys.stdout.write("\ufeff")
    writer = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in store().export_rows():
        writer.writerow({**row, "solved_at": iso(row["solved_at"]), "submitted_at": iso(row["submitted_at"])})
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
