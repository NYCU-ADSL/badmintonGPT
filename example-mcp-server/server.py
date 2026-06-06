#!/usr/bin/env python3
"""example-mcp — a minimal but complete remote MCP server (Streamable HTTP).

Demonstrates every pattern in the guide:
  - sync tools:  add, echo
  - async job:   start_render -> get_render_status -> get_render_result
  - file output: get_render_result returns a URL served by GET /files/{job_id}
  - health:      GET /healthz

Run:  python server.py      (serves MCP at http://127.0.0.1:8900/mcp)
Env:  MCP_HOST (default 127.0.0.1), MCP_PORT (8900), PUBLIC_BASE_URL, OUTPUT_DIR
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")   # bind localhost; expose via Cloudflare Tunnel
MCP_PORT = int(os.getenv("MCP_PORT", "8900"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", f"http://{MCP_HOST}:{MCP_PORT}")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/example-mcp-files"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

mcp = FastMCP("example-mcp", host=MCP_HOST, port=MCP_PORT)

# In-memory job store. DEMO ONLY — use a DB/redis/file for production (survives restarts).
JOBS: dict[str, dict] = {}


# ---- sync tools ---------------------------------------------------------------
@mcp.tool()
def add(a: float, b: float) -> dict:
    """Add two numbers and return {"sum": a+b}."""
    return {"sum": a + b}


@mcp.tool()
def echo(text: str) -> dict:
    """Echo text back as {"text": ...}. Validates input is a non-empty string."""
    if not isinstance(text, str) or not text:
        return {"error": "text must be a non-empty string"}
    return {"text": text}


# ---- async job (start -> status -> result), with file output ------------------
def _run_render(job_id: str, spec: dict) -> None:
    try:
        JOBS[job_id] |= {"state": "running"}
        time.sleep(2)  # pretend this is heavy work (video/render/GPU/etc.)
        out = OUTPUT_DIR / f"{job_id}.txt"
        out.write_text(f"rendered with spec={spec}\n", encoding="utf-8")
        JOBS[job_id] |= {"state": "succeeded", "path": str(out)}
    except Exception as e:  # noqa: BLE001
        JOBS[job_id] |= {"state": "failed", "error": str(e)}


@mcp.tool()
def start_render(spec: dict | None = None) -> dict:
    """Start a long render job. Returns {job_id, state} immediately (async)."""
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"state": "queued"}
    threading.Thread(target=_run_render, args=(job_id, spec or {}), daemon=True).start()
    return {"job_id": job_id, "state": "queued"}


@mcp.tool()
def get_render_status(job_id: str) -> dict:
    """Return {state, error?} for a render job. state in queued|running|succeeded|failed."""
    j = JOBS.get(job_id)
    if not j:
        return {"error": f"no such job: {job_id}"}
    return {"job_id": job_id, "state": j["state"], "error": j.get("error")}


@mcp.tool()
def get_render_result(job_id: str) -> dict:
    """Return {ready, url} when succeeded. url is downloadable over HTTP (not a local path)."""
    j = JOBS.get(job_id) or {}
    if j.get("state") != "succeeded":
        return {"ready": False, "state": j.get("state")}
    return {"ready": True, "url": f"{PUBLIC_BASE_URL}/files/{job_id}"}


# ---- plain HTTP routes (not MCP tools) ----------------------------------------
@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request):
    return JSONResponse({"ok": True})


@mcp.custom_route("/files/{job_id}", methods=["GET"])
async def serve_file(request: Request):
    job_id = request.path_params["job_id"]
    j = JOBS.get(job_id)
    if not j or j.get("state") != "succeeded" or not j.get("path"):
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(j["path"], media_type="text/plain", filename=f"{job_id}.txt")


def main() -> None:
    mcp.run(transport="streamable-http")  # MCP endpoint mounted at /mcp


if __name__ == "__main__":
    main()
