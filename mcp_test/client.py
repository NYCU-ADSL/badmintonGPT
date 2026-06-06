"""MCP connection helpers — wrap the official SDK transports into a ClientSession."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


@asynccontextmanager
async def open_http(url: str, headers: dict[str, str] | None):
    """Connect to a remote MCP over Streamable HTTP."""
    async with streamablehttp_client(url, headers=headers or None) as (read, write, _get_sid):
        async with ClientSession(read, write) as session:
            yield session


@asynccontextmanager
async def open_stdio(command: str, args: list[str], env: dict[str, str] | None):
    """Spawn and connect to a local MCP over stdio."""
    params = StdioServerParameters(
        command=command, args=args, env={**os.environ, **(env or {})}
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            yield session
