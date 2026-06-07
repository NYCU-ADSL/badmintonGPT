#!/usr/bin/env python3
"""Minimal self-contained smoke test for a remote MCP server.

Connects over Streamable HTTP, lists tools, calls `add`, then runs the async render
job (start -> poll status -> get result URL) and downloads the file.

Usage:
  python smoke_test.py http://127.0.0.1:8900/mcp
  python smoke_test.py https://example-mcp.<zone>/mcp \
      --header "CF-Access-Client-Id: $ID" --header "CF-Access-Client-Secret: $SECRET"

Deps: mcp  (pip install mcp)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _payload(result):
    """Extract a tool result as Python data (structured content or JSON text)."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
    try:
        return json.loads(text)
    except Exception:
        return text


def _headers(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, _, v = it.partition(":")
        out[k.strip()] = v.strip()
    return out


async def run(url: str, headers: dict[str, str]) -> None:
    async with streamablehttp_client(url, headers=headers or None) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print("tools:", tools)

            print("add(2,3) ->", _payload(await s.call_tool("add", {"a": 2, "b": 3})))

            start = _payload(await s.call_tool("start_render", {"spec": {"demo": True}}))
            job_id = start["job_id"]
            print("start_render ->", start)
            for _ in range(20):
                st = _payload(await s.call_tool("get_render_status", {"job_id": job_id}))
                # stage/total_stages/message are what an agent UI turns into a progress bar
                print(f"status -> {st.get('state')} {st.get('stage')}/{st.get('total_stages')} {st.get('message', '')}")
                if st.get("state") in ("succeeded", "failed"):
                    break
                await asyncio.sleep(1)
            res = _payload(await s.call_tool("get_render_result", {"job_id": job_id}))
            print("result ->", res)
            assert res.get("ready") and res.get("url"), "render did not produce a URL"
            print("OK ✅")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="MCP endpoint, e.g. http://127.0.0.1:8900/mcp")
    ap.add_argument("--header", action="append", default=[], help='HTTP header "K: V" (repeatable)')
    args = ap.parse_args()
    asyncio.run(run(args.url, _headers(args.header)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
