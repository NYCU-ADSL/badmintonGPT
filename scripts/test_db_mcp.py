#!/usr/bin/env python3
"""Standalone smoke test for the badminton-db stdio MCP server.

Launches db_mcp/server.py over stdio, lists tools, and exercises
list_tables / describe_table / query (incl. a rejected non-SELECT).
Run: python scripts/test_db_mcp.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
SERVER = str(ROOT / "db_mcp" / "server.py")
DB = os.environ.get("BADMINTON_DB", str(ROOT / "data" / "badminton.db"))


def _payload(result):
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    parts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
    txt = "\n".join(parts)
    try:
        return json.loads(txt)
    except Exception:
        return txt


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=[SERVER],
        env={**os.environ, "BADMINTON_DB": DB})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            r = await session.call_tool("list_tables", {})
            print("list_tables ->", _payload(r))

            r = await session.call_tool("describe_table", {"table": "shots"})
            cols = _payload(r)
            ncols = len(cols) if isinstance(cols, list) else cols
            print("describe_table(shots) -> cols:", ncols)

            r = await session.call_tool(
                "query", {"sql": "SELECT COUNT(*) n FROM shots "
                                 "WHERE type='殺球' AND player='A' AND win_reason IS NOT NULL"})
            print("query smash winners ->", _payload(r))

            r = await session.call_tool(
                "query", {"sql": "SELECT name FROM matches WHERE name LIKE '%AXELSEN%'"})
            p = _payload(r)
            print("query Axelsen matches -> row_count:",
                  p.get("row_count") if isinstance(p, dict) else p)

            r = await session.call_tool("query", {"sql": "DELETE FROM shots"})
            print("query DELETE (should be rejected) ->", _payload(r))

            r = await session.call_tool(
                "query", {"sql": "SELECT 1; DROP TABLE shots"})
            print("query multi-stmt (should be rejected) ->", _payload(r))


if __name__ == "__main__":
    asyncio.run(main())
