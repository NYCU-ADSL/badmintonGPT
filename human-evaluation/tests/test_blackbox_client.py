import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackbox_client import collect_output


class Socket:
    def __init__(self, frames):
        self.frames = iter([{"event": "ready", "chat_id": "new-session"}, *frames])
        self.sent = []

    async def recv(self):
        return json.dumps(next(self.frames), ensure_ascii=False)

    async def send(self, data):
        self.sent.append(json.loads(data))


def run(socket, query, path, model="gpt-5.6-luna"):
    return asyncio.run(collect_output(socket, query, path, "gpt-5.6-luna", {"model_name": model}))


def test_only_query_is_sent_and_output_is_preserved(tmp_path):
    frames = [
        {"event": "stream_end", "stream_id": "tool-only-turn"},
        {"event": "message", "kind": "tool_hint", "text": "generate_reel(enable_anchor=true)"},
        {"event": "message", "kind": "progress", "text": "Waiting for the service"},
        {"event": "delta", "stream_id": "1", "text": "  Original\n"},
        {"event": "delta", "stream_id": "1", "text": "reply: anchor unavailable.  "},
        {"event": "stream_end", "stream_id": "1"},
        {"event": "turn_end"},
    ]
    socket = Socket(frames)
    query = "  Please make a video.\n"
    result = run(socket, query, tmp_path)
    assert socket.sent == [{"type": "message", "chat_id": "new-session", "content": query, "webui": True}]
    assert result["messages"] == [{"text": "  Original\nreply: anchor unavailable.  ", "media_urls": []}]
    assert [json.loads(line) for line in (tmp_path / "output-frames.jsonl").read_text().splitlines()] == frames
    # No second query, /stop command, tool call, or fallback is sent.
    with pytest.raises(RuntimeError, match="already submitted"):
        run(socket, query, tmp_path)
    assert len(socket.sent) == 1


def test_native_final_text_and_media_are_unchanged(tmp_path):
    socket = Socket([
        {"event": "delta", "text": "![plot](/local/path.png)"},
        {"event": "stream_end", "text": "![plot](/api/media/signed/path?sig=abc)"},
        {"event": "message", "text": "", "media_urls": [{"url": "https://example.org/movie.mp4", "name": "movie.mp4"}]},
        {"event": "turn_end"},
    ])
    result = run(socket, "query", tmp_path)
    assert result["messages"] == [
        {"text": "![plot](/api/media/signed/path?sig=abc)", "media_urls": []},
        {"text": "", "media_urls": [{"url": "https://example.org/movie.mp4", "name": "movie.mp4"}]},
    ]


def test_model_mismatch_does_not_change_model_or_send_query(tmp_path):
    socket = Socket([])
    with pytest.raises(RuntimeError, match="Gateway model"):
        run(socket, "query", tmp_path, model="another-model")
    assert socket.sent == []


def test_transport_error_is_saved_without_retry_or_synthetic_answer(tmp_path):
    socket = Socket([{"event": "error", "detail": "unavailable"}])
    with pytest.raises(RuntimeError, match="unavailable"):
        run(socket, "query", tmp_path)
    assert len(socket.sent) == 1
    assert 'unavailable' in (tmp_path / "output-frames.jsonl").read_text()
    assert not (tmp_path / "output.json").exists()
