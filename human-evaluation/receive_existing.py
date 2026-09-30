"""Keep receiving an existing gateway conversation without sending a query.

Uses the same read-only `attach` envelope as opening an existing WebUI chat.
Saves output separately; never changes the live generator's files or dataset.
"""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from websockets.asyncio.client import connect

HERE = Path(__file__).resolve().parent


async def receive(dataset, item, gateway):
    artifact = HERE / "data" / dataset / "generation" / item / "gateway"
    request = json.loads((artifact / "request.json").read_text())
    chat_id = request["envelope"]["chat_id"]
    out = artifact / "reconnected"
    out.mkdir(exist_ok=True)
    async with httpx.AsyncClient(base_url=gateway, timeout=30) as client:
        response = await client.get("/webui/bootstrap")
        response.raise_for_status()
        boot = response.json()
        ws_base = gateway.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        url = ws_base.rstrip("/") + boot["ws_path"] + "?" + urlencode({"token": boot["token"]})
        async with connect(url, max_size=40 * 1024 * 1024) as socket:
            ready = json.loads(await socket.recv())
            assert ready["event"] == "ready"
            subscription = {"type": "attach", "chat_id": chat_id}
            (out / "subscription.json").write_text(json.dumps(subscription) + "\n")
            with (out / "output-frames.jsonl").open("x") as frames:
                await socket.send(json.dumps(subscription))
                print(f"Receiving existing conversation {chat_id}; no query sent", flush=True)
                while True:
                    raw = await socket.recv()
                    frames.write(raw + "\n")
                    frames.flush()
                    event = json.loads(raw)
                    if event.get("chat_id") == chat_id and event.get("event") == "turn_end":
                        break
        # Refresh the read token; the first token may have expired while waiting.
        response = await client.get("/webui/bootstrap")
        response.raise_for_status()
        token = response.json()["token"]
        response = await client.get("/api/sessions/" + quote("websocket:" + chat_id, safe="") + "/webui-thread",
                                    headers={"Authorization": "Bearer " + token})
        response.raise_for_status()
        (out / "native-thread.json").write_text(response.text)
        print("Saved the gateway's original conversation output", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="preview-10-blackbox")
    parser.add_argument("--item", required=True)
    parser.add_argument("--gateway", default="http://gateway:8765")
    args = parser.parse_args()
    asyncio.run(receive(args.dataset, args.item, args.gateway))
