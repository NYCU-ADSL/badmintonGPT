"""Screen inbound chat text with the OpenAI moderation endpoint before the agent sees it.

[badmintonGPT fork] Opt-in with ``NANOBOT_MODERATION=1``; the WebSocket channel calls
:func:`check` for every user message (slash commands excepted) and refuses flagged ones with an
``error`` event ``content_flagged``.

The endpoint's own ``flagged`` verdict is NOT used: badminton talk ("net kill", 殺球, 一擊必殺,
把對手殺爆) scores up to 0.85 on ``violence`` and 0.62 on ``illicit``, so a message is blocked
only when a category score reaches its threshold below. ``violence`` and ``illicit`` are
therefore set high; requests they let through are still refused by the chat model itself.

Fail-open: a timeout, HTTP error or missing key logs a warning and lets the message through, so
an outage of the moderation endpoint never takes the chat down with it.

Environment:

``NANOBOT_MODERATION``             ``1`` enables the check.
``NANOBOT_MODERATION_MODEL``       default ``omni-moderation-latest``.
``NANOBOT_MODERATION_API_KEY``     default ``OPENAI_API_KEY``.
``NANOBOT_MODERATION_API_BASE``    default ``https://api.openai.com/v1``.
``NANOBOT_MODERATION_THRESHOLDS``  JSON ``{"<category>": score}`` merged over the defaults; a
                                   value above 1 turns a category off.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

_TRUTHY = {"1", "true", "yes", "on"}

# Tuned on badminton questions vs. clearly harmful requests (see the module docstring).
DEFAULT_THRESHOLDS: dict[str, float] = {
    "sexual/minors": 0.3,
    "sexual": 0.5,
    "self-harm": 0.5,
    "self-harm/intent": 0.5,
    "self-harm/instructions": 0.5,
    "hate": 0.5,
    "hate/threatening": 0.5,
    "harassment": 0.5,
    "harassment/threatening": 0.5,
    "violence/graphic": 0.5,
    "illicit/violent": 0.7,
    "illicit": 0.85,
    "violence": 0.9,
}

# The endpoint accepts a list of inputs; long messages are checked piece by piece so padding a
# harmful request with filler cannot push it past a truncation point.
CHUNK_CHARS = 4000
MAX_CHUNKS = 32
TIMEOUT_S = 8.0


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    categories: list[str] = field(default_factory=list)

    @property
    def self_harm(self) -> bool:
        return any(c.startswith("self-harm") for c in self.categories)


ALLOWED = Verdict(blocked=False)


def enabled() -> bool:
    return os.environ.get("NANOBOT_MODERATION", "").strip().lower() in _TRUTHY


def thresholds() -> dict[str, float]:
    table = dict(DEFAULT_THRESHOLDS)
    raw = os.environ.get("NANOBOT_MODERATION_THRESHOLDS", "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            if isinstance(extra, dict):
                table.update({str(k): float(v) for k, v in extra.items()})
        except (ValueError, TypeError) as exc:
            logger.warning("invalid NANOBOT_MODERATION_THRESHOLDS ignored: {}", exc)
    return table


def verdict_from_results(results: list[dict[str, Any]], table: dict[str, float]) -> Verdict:
    hit: set[str] = set()
    for result in results:
        scores = result.get("category_scores") or {}
        for category, limit in table.items():
            score = scores.get(category)
            if isinstance(score, (int, float)) and score >= limit:
                hit.add(category)
    return Verdict(blocked=bool(hit), categories=sorted(hit))


def _chunks(text: str) -> list[str]:
    pieces = [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]
    if len(pieces) > MAX_CHUNKS:
        logger.warning("moderation: message of {} chars checked only in its first {} chars",
                       len(text), CHUNK_CHARS * MAX_CHUNKS)
    return pieces[:MAX_CHUNKS]


async def check(text: str, *, client: httpx.AsyncClient | None = None) -> Verdict:
    """Moderate *text*. Returns :data:`ALLOWED` when disabled, empty, or on any failure."""
    if not enabled() or not text or not text.strip():
        return ALLOWED
    key = os.environ.get("NANOBOT_MODERATION_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        logger.warning("moderation: no API key; message not checked")
        return ALLOWED
    base = os.environ.get("NANOBOT_MODERATION_API_BASE", "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": os.environ.get("NANOBOT_MODERATION_MODEL", "omni-moderation-latest"),
        "input": _chunks(text),
    }
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as owned:
                resp = await owned.post(
                    f"{base}/moderations", json=body, headers={"Authorization": f"Bearer {key}"}
                )
        else:
            resp = await client.post(
                f"{base}/moderations", json=body, headers={"Authorization": f"Bearer {key}"}
            )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception as exc:  # fail-open: see module docstring
        logger.warning("moderation: check failed, message let through: {}", exc)
        return ALLOWED
    return verdict_from_results(results, thresholds())
