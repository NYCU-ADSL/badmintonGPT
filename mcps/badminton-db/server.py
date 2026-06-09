#!/usr/bin/env python3
"""badminton-db — MCP server over the read-only badminton SQLite DB.

Tools:
  - list_tables()            -> [table names]
  - describe_table(table)    -> [{cid, name, type, ...}]   (PRAGMA table_info)
  - query(sql)               -> {rows, row_count}          (single SELECT only)

Transport (env MCP_TRANSPORT): "streamable-http" (default — served at /mcp on
MCP_HOST:MCP_PORT for its own container) or "stdio" (used by scripts/test_db_mcp.py).
Security: opens the DB with mode=ro and only accepts a single SELECT statement.
Depends only on `mcp` + stdlib `sqlite3` (no badminton package needed).
Env: BADMINTON_DB = path to badminton.db; MCP_HOST (default 0.0.0.0); MCP_PORT (8801).
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

mcp = FastMCP(
    "badminton-db",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8801")),
)

DB_PATH = os.environ.get("BADMINTON_DB", "")
ROW_LIMIT = 200
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SELECT = re.compile(r"^\s*select\b", re.IGNORECASE)


def _connect() -> sqlite3.Connection:
    if not DB_PATH:
        raise RuntimeError("BADMINTON_DB env var is not set")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@mcp.tool()
def list_tables() -> list[str]:
    """List the tables in the badminton database."""
    conn = _connect()
    try:
        return [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    finally:
        conn.close()


@mcp.tool()
def describe_table(
    table: Annotated[str, Field(
        description="Name of the table to inspect (e.g. 'matches', 'rallies', "
                    "or 'shots'). Must be a valid SQL identifier.")],
) -> list[dict]:
    """Return column info (name, type, ...) for a table via PRAGMA table_info."""
    if not _IDENT.match(table):
        return [{"error": f"invalid table name: {table!r}"}]
    conn = _connect()
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            return [{"error": f"no such table: {table}"}]
        return [dict(r) for r in rows]
    finally:
        conn.close()


@mcp.tool()
def query(
    sql: Annotated[str, Field(
        description="A single read-only SELECT statement to run against the "
                    "badminton DB. At most 200 rows are returned. Multiple "
                    "statements, a trailing extra statement, or any non-SELECT "
                    "query are rejected.")],
) -> dict:
    """Run a single read-only SELECT and return {rows, row_count} (max 200 rows).

    Only one SELECT statement is allowed; anything else is rejected.
    """
    stripped = sql.strip().rstrip(";")
    if not _SELECT.match(stripped) or ";" in stripped:
        return {"error": "only a single SELECT statement is allowed"}
    conn = _connect()
    try:
        rows = [dict(r) for r in conn.execute(stripped).fetchmany(ROW_LIMIT)]
        return {"rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    """Liveness probe (used by the container healthcheck). No DB access."""
    return JSONResponse({"ok": True})


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run()  # stdio transport (scripts/test_db_mcp.py)
    else:
        mcp.run(transport="streamable-http")  # MCP endpoint mounted at /mcp


if __name__ == "__main__":
    main()
