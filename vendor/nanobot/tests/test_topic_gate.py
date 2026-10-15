"""Badminton-only topic gate (NANOBOT_TOPIC_GATE). [badmintonGPT fork]"""

from __future__ import annotations

import json

import httpx
import pytest

from nanobot import topic_gate


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("NANOBOT_TOPIC_GATE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("NANOBOT_TOPIC_GATE_API_KEY", raising=False)
    monkeypatch.delenv("NANOBOT_TOPIC_GATE_MODEL", raising=False)


def _reply(in_scope: object) -> dict:
    return {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [
                {"type": "output_text", "text": json.dumps({"in_scope": in_scope})},
            ]},
        ],
        "usage": {"input_tokens": 380, "output_tokens": 13,
                  "input_tokens_details": {"cached_tokens": 0}},
    }


def test_context_keeps_recent_text_turns():
    messages = [{"role": "user", "content": f"q{i}"} for i in range(10)] + [
        {"role": "assistant", "content": None, "tool_calls": [{}]},
        {"role": "tool", "content": "rows"},
        {"role": "assistant", "content": [{"type": "text", "text": "21–12,  21–16"}]},
    ]
    ctx = topic_gate.context_from_messages(messages)
    assert len(ctx) == topic_gate.CONTEXT_TURNS
    assert ctx[-1] == ("assistant", "21–12, 21–16")
    text = topic_gate.build_input("那第二局呢？", ctx)
    assert text.endswith("LATEST user message:\n那第二局呢？") and "[user] q9" in text


async def test_check_sends_context_and_reads_the_verdict():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json=_reply("CPU" not in body["input"]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await topic_gate.check("畫成長條圖", [("user", "周天成比分？")], client=client)
        off = await topic_gate.check("目前 CPU 負載率多少", [], client=client)
    assert ok.in_scope and not off.in_scope
    assert off.model == "gpt-6-luna" and off.usage == {
        "prompt_tokens": 380, "completion_tokens": 13, "cached_tokens": 0,
    }
    assert seen[0]["reasoning"] == {"effort": "low"} and seen[0]["store"] is False
    assert "周天成比分" in seen[0]["input"] and "badminton" in seen[0]["instructions"]


async def test_fail_open_and_disabled(monkeypatch):
    async def run(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await topic_gate.check("anything", [], client=client)

    assert await run(lambda r: httpx.Response(500)) is topic_gate.ALLOWED
    assert await run(lambda r: httpx.Response(200, json=_reply("no"))) is topic_gate.ALLOWED
    assert await run(lambda r: httpx.Response(200, json={"output": []})) is topic_gate.ALLOWED
    monkeypatch.setenv("NANOBOT_TOPIC_GATE", "0")
    assert await topic_gate.check("anything", []) is topic_gate.ALLOWED
