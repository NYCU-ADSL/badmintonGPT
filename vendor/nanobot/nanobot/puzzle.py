"""Link-only puzzle answer page: server-side check + per-account wrong-answer cooldown.

[badmintonGPT fork] Serves ``/puzzle.html`` (a static page, behind Cloudflare Access like every
path except ``/welcome.html``) through ``GET /api/puzzle`` and ``GET /api/puzzle/answer``
in ``channels/websocket.py``. The answer never reaches the browser: it lives only in the
``NANOBOT_PUZZLE_ANSWER`` env var (repo-root ``.env``) and is compared here.

After the n-th wrong answer the account must wait n/2 minutes before it may answer again
(30 s, 1 min, 1.5 min, ...). Attempts are stored per e-mail in SQLite
(``NANOBOT_PUZZLE_DB``, default ``<data dir>/puzzle.db``) so a restart does not reset them.

Env:
``NANOBOT_PUZZLE_ANSWER``  the accepted answer; unset/empty → the page reports "not configured".
``NANOBOT_PUZZLE_DB``      optional SQLite path override.
"""

from __future__ import annotations

import hmac
import os
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from loguru import logger

# Each wrong answer adds half a minute to the wait before the next attempt.
COOLDOWN_PER_WRONG_S = 30.0
MAX_ANSWER_CHARS = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS puzzle_attempts (
    email        TEXT PRIMARY KEY,
    wrong_count  INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0,
    solved_at    REAL
);
"""


def configured_answer() -> str:
    return normalize_answer(os.environ.get("NANOBOT_PUZZLE_ANSWER", ""))


def normalize_answer(value: str) -> str:
    """NFKC (full-width → half-width) and drop all whitespace, so 「謎 底」 matches 「謎底」."""
    return "".join(unicodedata.normalize("NFKC", value or "").split())


def cooldown_s(wrong_count: int) -> float:
    return wrong_count * COOLDOWN_PER_WRONG_S


class PuzzleStore:
    """Per-account attempt state. Thread-safe; every call is one short transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _row(self, email: str) -> tuple[int, float, float | None]:
        row = self._db.execute(
            "SELECT wrong_count, locked_until, solved_at FROM puzzle_attempts WHERE email = ?",
            (email,),
        ).fetchone()
        return (int(row[0]), float(row[1]), row[2]) if row else (0, 0.0, None)

    @staticmethod
    def _payload(wrong: int, locked_until: float, solved_at: float | None, now: float) -> dict[str, Any]:
        return {
            "configured": True,
            "solved": solved_at is not None,
            "wrong_count": wrong,
            "retry_after_s": 0 if solved_at is not None else max(0, round(locked_until - now)),
        }

    def status(self, email: str, *, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            wrong, locked_until, solved_at = self._row(email)
        return self._payload(wrong, locked_until, solved_at, now)

    def attempt(self, email: str, answer: str, expected: str, *, now: float | None = None) -> dict[str, Any]:
        """Check *answer*. Refused (``accepted=False``) while cooling down or once solved."""
        now = time.time() if now is None else now
        with self._lock:
            wrong, locked_until, solved_at = self._row(email)
            if solved_at is not None or now < locked_until:
                body = self._payload(wrong, locked_until, solved_at, now)
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
        return {**self._payload(wrong, locked_until, solved_at, now), "accepted": True, "correct": correct}


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
