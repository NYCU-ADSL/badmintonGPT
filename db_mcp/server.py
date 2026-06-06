#!/usr/bin/env python3
"""badminton-db — local stdio MCP server over the read-only badminton SQLite DB.

Tools:
  - list_tables()            -> [table names]
  - describe_table(table)    -> [{cid, name, type, ...}]   (PRAGMA table_info)
  - query(sql)               -> {rows, row_count}          (single SELECT only)

Security: opens the DB with mode=ro and only accepts a single SELECT statement.
Depends only on `mcp` + stdlib `sqlite3` (no badminton package needed).
Env: BADMINTON_DB = path to badminton.db
"""
from __future__ import annotations

import os
import re
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("badminton-db")

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
def describe_table(table: str) -> list[dict]:
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
def query(sql: str) -> dict:
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


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
