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
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
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
def add(
    a: Annotated[float, Field(description="First number to add.")],
    b: Annotated[float, Field(description="Second number to add.")],
) -> dict:
    """Add two numbers and return {"sum": a+b}."""
    return {"sum": a + b}


@mcp.tool()
def echo(
    text: Annotated[str, Field(description="Text to echo back; must be a non-empty string.")],
) -> dict:
    """Echo text back as {"text": ...}. Validates input is a non-empty string."""
    if not isinstance(text, str) or not text:
        return {"error": "text must be a non-empty string"}
    return {"text": text}


# ---- async job (start -> status -> result), with file output ------------------
# Progress reporting: the worker updates stage/total_stages/message as it goes, and
# get_render_status echoes them. Consuming agents/UIs use these fields to render a
# live progress bar. Derive the total from the actual step list — never hardcode it
# somewhere else, or the bar will desync when you add a step.
RENDER_STEPS = ["preparing assets", "rendering frames", "encoding output"]


def _run_render(job_id: str, spec: dict) -> None:
    try:
        total = len(RENDER_STEPS)
        for i, step in enumerate(RENDER_STEPS, start=1):
            JOBS[job_id] |= {
                "state": "running",
                "stage": i,
                "total_stages": total,
                "message": f"[{i}/{total}] {step}",
            }
            time.sleep(1)  # pretend each step is heavy work (video/render/GPU/etc.)
        out = OUTPUT_DIR / f"{job_id}.txt"
        out.write_text(f"rendered with spec={spec}\n", encoding="utf-8")
        JOBS[job_id] |= {"state": "succeeded", "stage": total, "message": "done", "path": str(out)}
    except Exception as e:  # noqa: BLE001
        JOBS[job_id] |= {"state": "failed", "error": str(e)}


@mcp.tool()
def start_render(
    spec: Annotated[dict | None, Field(
        description="Optional free-form render spec (JSON object) passed through "
                    "to the job; omit for defaults.")] = None,
) -> dict:
    """Start a long render job. Returns {job_id, state} immediately (async)."""
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"state": "queued", "stage": 0, "total_stages": len(RENDER_STEPS), "message": "queued"}
    threading.Thread(target=_run_render, args=(job_id, spec or {}), daemon=True).start()
    return {"job_id": job_id, "state": "queued"}


@mcp.tool()
def get_render_status(
    job_id: Annotated[str, Field(description="The job_id returned by start_render.")],
) -> dict:
    """Return job progress: {job_id, state, stage, total_stages, message, error?}.

    state in queued|running|succeeded|failed. stage/total_stages/message let the
    calling agent/UI show a live progress bar. Must return immediately (clients poll).
    """
    j = JOBS.get(job_id)
    if not j:
        return {"error": f"no such job: {job_id}"}
    return {
        "job_id": job_id,
        "state": j["state"],
        "stage": j.get("stage", 0),
        "total_stages": j.get("total_stages", 0),
        "message": j.get("message", ""),
        "error": j.get("error"),
    }


@mcp.tool()
def get_render_result(
    job_id: Annotated[str, Field(description="The job_id returned by start_render.")],
) -> dict:
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
