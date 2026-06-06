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

## Layout
- `server.py` — the MCP server.
- `smoke_test.py` — minimal MCP client to verify it.
- `.env.example` — config (copy to `.env`).
- `deploy/` — Cloudflare Tunnel config + systemd unit templates for going remote.

Full build/deploy/consume reference: **https://badmintongpt-docs.nycu-adsl.cc**
