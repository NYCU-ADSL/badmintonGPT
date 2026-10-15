"""Inbound chat moderation: per-category thresholds, chunking, fail-open. [badmintonGPT fork]"""

from __future__ import annotations

import json

import httpx
import pytest

from nanobot import moderation

# Real omni-moderation-latest scores (2026-10-13) for a badminton question it flags on its own
# and for clearly harmful requests.
NET_KILL = {"violence": 0.51, "illicit": 0.21, "illicit/violent": 0.17}
SMASH_THEM = {"violence": 0.85, "illicit": 0.21, "illicit/violent": 0.11}
BACKHAND_ATTACK = {"illicit": 0.62, "illicit/violent": 0.52, "violence": 0.35}
PIPE_BOMB = {"illicit": 0.96, "illicit/violent": 0.95, "violence": 0.02}
SUICIDE = {"self-harm/intent": 0.99, "self-harm": 0.97, "self-harm/instructions": 0.54}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("NANOBOT_MODERATION", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("NANOBOT_MODERATION_API_KEY", raising=False)
    monkeypatch.delenv("NANOBOT_MODERATION_THRESHOLDS", raising=False)


def _results(*scores: dict[str, float]) -> list[dict]:
    return [{"flagged": True, "category_scores": s} for s in scores]


def test_badminton_wording_passes_but_harm_is_blocked():
    table = moderation.thresholds()
    for benign in (NET_KILL, SMASH_THEM, BACKHAND_ATTACK):
        assert not moderation.verdict_from_results(_results(benign), table).blocked
    bomb = moderation.verdict_from_results(_results(PIPE_BOMB), table)
    assert bomb.blocked and bomb.categories == ["illicit", "illicit/violent"]
    assert not bomb.self_harm
    assert moderation.verdict_from_results(_results(SUICIDE), table).self_harm


def test_threshold_override(monkeypatch):
    monkeypatch.setenv("NANOBOT_MODERATION_THRESHOLDS", json.dumps({"violence": 0.5, "illicit": 2}))
    table = moderation.thresholds()
    assert moderation.verdict_from_results(_results(NET_KILL), table).categories == ["violence"]
    assert moderation.verdict_from_results(_results(PIPE_BOMB), table).categories == [
        "illicit/violent"
    ]


async def test_check_sends_chunks_and_reads_scores():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["Authorization"] == "Bearer sk-test"
        scores = [PIPE_BOMB if "bomb" in piece else NET_KILL for piece in body["input"]]
        return httpx.Response(200, json={"results": _results(*scores)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = "a" * (moderation.CHUNK_CHARS + 10) + " pipe bomb"
        verdict = await moderation.check(text, client=client)
    assert verdict.blocked
    assert len(seen[0]["input"]) == 2 and seen[0]["model"] == "omni-moderation-latest"


async def test_fail_open_and_disabled(monkeypatch):
    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as client:
        assert await moderation.check("anything", client=client) is moderation.ALLOWED
    monkeypatch.delenv("OPENAI_API_KEY")
    assert await moderation.check("anything") is moderation.ALLOWED
    monkeypatch.setenv("NANOBOT_MODERATION", "0")
    assert await moderation.check("anything") is moderation.ALLOWED
