"""Verify saved text against received frames and compare native WebUI history.

This verifier never sends a query, edits a session, or changes stored answers.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import quote

import httpx

HERE = Path(__file__).resolve().parent


def wire_texts(path):
    # Independently group the actual wire text by server-provided stream IDs.
    # History replay can omit earlier segments; never use it to trim an answer.
    segments = {}
    fallback = 0
    for index, line in enumerate(path.read_text().splitlines()):
        event = json.loads(line)
        kind = event.get("event")
        key = ("stream", event.get("stream_id", fallback))
        if kind == "delta":
            segments[key] = segments.get(key, "") + event["text"]
        elif kind == "stream_end":
            if isinstance(event.get("text"), str):
                segments[key] = event["text"]
            fallback += 1
        elif kind == "message" and event.get("kind") not in ("progress", "tool_hint", "reasoning"):
            segments[("message", index)] = event.get("text", "")
    return [text for text in segments.values() if text]


def verify(dataset, gateway):
    root = HERE / "data" / dataset
    rows = json.loads((root / "dataset.json").read_text())["items"]
    reports = []
    with httpx.Client(base_url=gateway, timeout=30) as client:
        boot = client.get("/webui/bootstrap")
        boot.raise_for_status()
        client.headers["Authorization"] = "Bearer " + boot.json()["token"]
        for row in rows:
            artifact = root / "generation" / row["id"] / "gateway"
            request = json.loads((artifact / "request.json").read_text())
            output = json.loads((artifact / "output.json").read_text())
            response = client.get("/api/sessions/" + quote("websocket:" + row["gateway_chat_id"], safe="") + "/webui-thread")
            response.raise_for_status()
            native = response.json()
            # Compare actual conversation text, including whitespace. Tool traces
            # and reasoning are separate UI rows, preserved in raw frames instead.
            native_text = [m["content"] for m in native["messages"]
                           if m.get("role") == "assistant" and not m.get("kind") and m.get("content")]
            saved_text = [m["text"] for m in row["output_messages"] if m["text"]]
            native_queries = [m["content"] for m in native["messages"] if m.get("role") == "user"]
            result = {"id": row["id"], "model": row["model"],
                      "request_matches_query": request["envelope"]["content"] == row["query_en"],
                      "gateway_received_only_query": native_queries == [row["query_en"]],
                      "saved_output_matches_received": output["messages"] == row["output_messages"],
                      "text_matches_raw_frames": wire_texts(artifact / "output-frames.jsonl") == saved_text,
                      "text_matches_native_webui": native_text == saved_text}
            reports.append(result)
    contract_fields = ("request_matches_query", "gateway_received_only_query",
                       "saved_output_matches_received", "text_matches_raw_frames")
    passed = all(all(r[key] for key in contract_fields) for r in reports)
    out = HERE / "runtime" / "output-verification.json"
    out.write_text(json.dumps({"dataset": dataset, "passthrough_verified": passed,
                              "native_history_differences": [r["id"] for r in reports if not r["text_matches_native_webui"]],
                              "items": reports}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="preview-10-blackbox")
    parser.add_argument("--gateway", default="http://gateway:8765")
    args = parser.parse_args()
    verify(args.dataset, args.gateway)
