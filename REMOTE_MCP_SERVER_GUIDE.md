# Remote MCP Server Guide

Build, deploy, and consume a **remote MCP server** that any MCP client (agents, IDEs, etc.) can call
over the network. Reference implementation: **`example-mcp-server/`** (ships with this guide).

- **Protocol:** Model Context Protocol — see <https://modelcontextprotocol.io>
- **Transport:** Streamable HTTP (the MCP endpoint is mounted at `/mcp`)
- **SDK:** official `mcp` Python package (`FastMCP`)

Use a remote server (instead of a local stdio one) when the work is heavy/long-running, needs GPU,
must be shared across teams, or wraps an existing service.

---

## Quickstart

From `example-mcp-server/`:

```bash
uv sync                      # or: pip install mcp
python server.py             # serves MCP at http://127.0.0.1:8900/mcp

# verify (second shell)
curl -s http://127.0.0.1:8900/healthz            # -> {"ok": true}
python smoke_test.py http://127.0.0.1:8900/mcp   # lists tools, runs the async job, downloads a file
```

---

## Server reference

### Defining tools

A tool is a decorated function. Its **docstring** is what the client/agent reads to decide when to call
it, so make it precise. Return JSON-serializable data; on failure return `{"error": "..."}` rather than
raising. Validate inputs.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example-mcp", host="127.0.0.1", port=8900)

@mcp.tool()
def add(a: float, b: float) -> dict:
    """Add two numbers and return {"sum": a+b}."""
    return {"sum": a + b}

def main():
    mcp.run(transport="streamable-http")   # endpoint at /mcp
```

Tool naming: `^[A-Za-z0-9_-]+$`, unique, with a non-empty description and a valid JSON-Schema
`inputSchema` (FastMCP derives the schema from type hints automatically).

### HTTP endpoints

| Method & Path | Purpose | Auth |
|---|---|---|
| `POST /mcp` | MCP Streamable HTTP endpoint (initialize, tools/list, tools/call, …) | required |
| `GET /healthz` | Liveness probe → `{"ok": true}` | required* |
| `GET /files/{id}` | Download an artifact produced by a job | required* |

\* When deployed behind Cloudflare Access (below), every path on the hostname requires the service token.

Add non-MCP routes with `@mcp.custom_route`:

```python
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse

@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request):
    return JSONResponse({"ok": True})
```

### Async job contract (long tasks)

Never block a tool for minutes. Split long work into three tools:

| Tool | Input | Output |
|---|---|---|
| `start_<x>` | job spec | `{job_id, state}` |
| `get_<x>_status` | `job_id` | `{state, error?}` |
| `get_<x>_result` | `job_id` | `{ready, url, …}` |

`state ∈ {queued, running, succeeded, failed}`. The client calls `start_*`, polls `get_*_status` until
terminal, then `get_*_result`. See `start_render` / `get_render_status` / `get_render_result` in
`example-mcp-server/server.py` (a background thread does the work; the job store is in-memory for the
demo — use a DB/redis/file in production so it survives restarts).

### File delivery

Return a **downloadable URL**, never a local filesystem path (remote clients can't read your disk).
Serve artifacts from a route and build the URL from a public base:

```python
import os
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://example-mcp.<your-zone>")

@mcp.custom_route("/files/{job_id}", methods=["GET"])
async def serve_file(request: Request):
    job_id = request.path_params["job_id"]
    ...  # 404 if not ready
    return FileResponse(path, filename=f"{job_id}.bin")

# get_render_result returns: {"ready": True, "url": f"{PUBLIC_BASE_URL}/files/{job_id}"}
```

---

## Deployment

### 1. Run the server

Bind to `127.0.0.1` (only the tunnel reaches it). Configure via env:

| Var | Default | Purpose |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | bind address |
| `MCP_PORT` | `8900` | port |
| `PUBLIC_BASE_URL` | — | public origin for building file URLs |

### 2. Expose with Cloudflare Tunnel

No open ports, no public IP, no self-managed TLS. Requires a domain on Cloudflare.

```bash
cloudflared tunnel login
cloudflared tunnel create example-mcp
# edit ~/.cloudflared/config.yml  (template: deploy/cloudflared.config.example.yml)
cloudflared tunnel route dns example-mcp example-mcp.<your-zone>
cloudflared tunnel run example-mcp
```

`~/.cloudflared/config.yml` maps the hostname to your local server:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/<user>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: example-mcp.<your-zone>
    service: http://127.0.0.1:8900     # /mcp, /healthz, /files all go here
  - service: http_status:404
```

### 3. Protect with Cloudflare Access (service token)

A public endpoint must be gated or anyone can call your tools.

1. Zero Trust → **Access → Applications → Add → Self-hosted**; domain = `example-mcp.<your-zone>`.
2. **Access → Service Auth → Create Service Token** → copy **Client ID** and **Client Secret**.
3. Add a policy: **Action = Service Auth**, Include = that token.

Only requests carrying `CF-Access-Client-Id` / `CF-Access-Client-Secret` reach your origin; everything
else is blocked at Cloudflare's edge. Multiple servers should each use their **own** token, named per
server (e.g. `EXAMPLE_CF_CLIENT_ID` / `EXAMPLE_CF_CLIENT_SECRET`).

### 4. Keep it running (systemd)

Run both the server and the tunnel as user services so they survive crashes and reboots. Templates:
`deploy/example-mcp.service`, `deploy/cloudflared-example-mcp.service`.

```bash
systemctl --user daemon-reload
systemctl --user enable --now example-mcp cloudflared-example-mcp
loginctl enable-linger "$USER"      # survive logout / reboot
```

---

## Consuming the server

The client connects to `https://example-mcp.<your-zone>/mcp` with the service-token headers:

```python
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HEADERS = {
    "CF-Access-Client-Id": os.environ["EXAMPLE_CF_CLIENT_ID"],
    "CF-Access-Client-Secret": os.environ["EXAMPLE_CF_CLIENT_SECRET"],
}

async def main():
    async with streamablehttp_client("https://example-mcp.<your-zone>/mcp", headers=HEADERS) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
            print(await s.call_tool("add", {"a": 2, "b": 3}))

asyncio.run(main())
```

Agent frameworks register it the same way: a streamable-HTTP MCP server at the `/mcp` URL with those
two headers.

---

## Verification

```bash
# functional (bundled client): lists tools, calls add, runs the async job, downloads the file
python smoke_test.py https://example-mcp.<your-zone>/mcp \
  --header "CF-Access-Client-Id: $EXAMPLE_CF_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $EXAMPLE_CF_CLIENT_SECRET"

# health (with token) -> 200 {"ok":true}
curl -s -o /dev/null -w "%{http_code}\n" https://example-mcp.<your-zone>/healthz \
  -H "CF-Access-Client-Id: $EXAMPLE_CF_CLIENT_ID" -H "CF-Access-Client-Secret: $EXAMPLE_CF_CLIENT_SECRET"

# auth gating (no token) -> 401/403  (Access is protecting it)
curl -s -o /dev/null -w "%{http_code}\n" https://example-mcp.<your-zone>/healthz
```

---

## Checklist

- [ ] Server binds `127.0.0.1`; not exposed directly (tunnel only).
- [ ] Cloudflare Access service token set; all paths (incl. `/files`) protected.
- [ ] Secrets in env / `.env`, never committed.
- [ ] Inputs validated; tools return JSON, `{"error": ...}` on failure.
- [ ] Long tasks use the async job contract; tools never block.
- [ ] Artifacts returned as URLs, not local paths.
- [ ] `GET /healthz` present.
- [ ] Server + tunnel run under systemd (`Restart=always`, linger enabled).
