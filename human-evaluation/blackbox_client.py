"""Ordinary WebUI client: send one query and save the gateway's output.

No agent imports, tool hooks, injected instructions, retries, or job management.
The frames file is the unmodified WebSocket output; messages only assemble the
gateway's stream protocol, exactly as a client must do to display its response.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect


class OutputCollector:
    def __init__(self):
        self.messages = []
        self.streams = {}

    def feed(self, event):
        kind = event.get("event")
        if kind in ("delta", "stream_end"):
            key = event.get("stream_id", "")
            message = self.streams.get(key)
            if message is None and kind == "stream_end" and not event.get("text"):
                return
            if message is None:
                message = {"text": "", "media_urls": []}
                self.messages.append(message)
                self.streams[key] = message
            if kind == "delta":
                message["text"] += event.get("text", "")
            else:
                if isinstance(event.get("text"), str):
                    message["text"] = event["text"]
                self.streams.pop(key, None)
        elif kind == "message" and event.get("kind") not in ("progress", "tool_hint", "reasoning"):
            self.messages.append({"text": event.get("text", ""), "media_urls": event.get("media_urls", [])})


async def collect_output(socket, query, artifact, expected_model, bootstrap):
    """One send only. A disconnected/uncertain request is never resubmitted."""
    artifact = Path(artifact)
    artifact.mkdir(parents=True, exist_ok=True)
    request_path = artifact / "request.json"
    if request_path.exists():
        raise RuntimeError("A query was already submitted. Inspect its saved gateway output; no automatic resubmission.")
    if bootstrap.get("model_name") != expected_model:
        raise RuntimeError(f"Gateway model is {bootstrap.get('model_name')!r}, expected {expected_model!r}; no query sent")
    ready = json.loads(await socket.recv())
    if ready.get("event") != "ready":
        raise RuntimeError("Gateway did not send a ready event")
    chat_id = ready["chat_id"]
    envelope = {"type": "message", "chat_id": chat_id, "content": query, "webui": True}
    with request_path.open("x") as handle:
        json.dump({"model": bootstrap["model_name"], "envelope": envelope}, handle, ensure_ascii=False, indent=2)
    collector = OutputCollector()
    with (artifact / "output-frames.jsonl").open("x") as frames:
        await socket.send(json.dumps(envelope, ensure_ascii=False))
        while True:
            raw = await socket.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            frames.write(raw + "\n")
            frames.flush()
            event = json.loads(raw)
            if event.get("chat_id") not in (None, chat_id):
                continue
            collector.feed(event)
            if event.get("event") == "error":
                raise RuntimeError(f"Gateway transport error: {event.get('detail')}")
            if event.get("event") == "turn_end":
                break
    result = {"chat_id": chat_id, "model": bootstrap["model_name"], "messages": collector.messages}
    (artifact / "output.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


async def query_gateway(query, artifact, *, base_url, expected_model, timeout=1800):
    # HTTP bootstrap and WS envelopes are the same interface used by the WebUI.
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(base_url.rstrip("/") + "/webui/bootstrap")
        response.raise_for_status()
        bootstrap = response.json()
    ws_base = base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    url = ws_base.rstrip("/") + bootstrap["ws_path"] + "?" + urlencode({
        "token": bootstrap["token"], "client_id": "human-evaluation",
    })
    async with connect(url, max_size=40 * 1024 * 1024) as socket:
        async with asyncio.timeout(timeout):
            return await collect_output(socket, query, artifact, expected_model, bootstrap)
