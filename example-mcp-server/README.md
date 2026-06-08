# example-mcp-server

A minimal but complete **remote MCP server** (Streamable HTTP) — the reference implementation for the
[Remote MCP Server Guide](https://badmintongpt-docs.nycu-adsl.cc).

It demonstrates: sync tools (`add`, `echo`), an async job (`start_render` → `get_render_status` →
`get_render_result`), file delivery over HTTP (`GET /files/{id}`), and a health check (`GET /healthz`).

## Quickstart

```bash
uv sync                     # or: pip install mcp
python server.py            # serves MCP at http://127.0.0.1:8900/mcp

# in another shell:
curl -s http://127.0.0.1:8900/healthz          # {"ok": true}
python smoke_test.py http://127.0.0.1:8900/mcp # lists tools, runs the async job, downloads the file
```

## Run with Docker

```bash
docker build -t example-mcp .
docker run -p 8900:8900 example-mcp        # MCP at http://localhost:8900/mcp

# or, with the standalone demo compose (publishes the port + mounts ./demo-files):
docker compose up --build

# in another shell — same checks as the Quickstart:
curl -s http://localhost:8900/healthz            # {"ok": true}
python smoke_test.py http://localhost:8900/mcp   # lists tools, runs the async job, downloads the file
```

Notes:
- **No app-level auth.** Cloudflare Access is the security boundary when this is deployed; a plain
  `docker run` / `docker compose up` is unauthenticated, which is fine for a local demo.
- The image sets `MCP_HOST=0.0.0.0` (not `127.0.0.1`) so the port is reachable from the host and the
  compose network. The server binds inside the container; the published `-p 8900:8900` exposes it.
- The async-job state lives in an **in-memory `JOBS` dict** — it does **not** survive a restart, so a
  `job_id` from a previous container won't resolve after `docker restart`.
- Behind a Cloudflare Tunnel, set `PUBLIC_BASE_URL` to the public hostname (e.g.
  `https://example-mcp.<your-zone>`); otherwise the file URLs from `get_render_result` point at
  `http://127.0.0.1:8900` and won't be reachable by callers.

## Layout
- `server.py` — the MCP server.
- `Dockerfile` / `docker-compose.yml` / `.dockerignore` — the Docker demo (above).
- `smoke_test.py` — minimal MCP client to verify it.
- `.env.example` — config (copy to `.env`).
- `deploy/` — Cloudflare Tunnel config + systemd unit templates for going remote.

Full build/deploy/consume reference: **https://badmintongpt-docs.nycu-adsl.cc**
