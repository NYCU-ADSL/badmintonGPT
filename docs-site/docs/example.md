# Example server

A complete, runnable reference implementation of a remote MCP server. It demonstrates every pattern in
the [Guide](index.md): sync tools (`add`, `echo`), an async job
(`start_render` → `get_render_status` → `get_render_result`), file delivery over HTTP
(`GET /files/{id}`), and a health check (`GET /healthz`).

[:material-download: Download example-mcp-server.zip](example-mcp-server.zip){ .md-button .md-button--primary }

## Run it

```bash
cd example-mcp-server
uv sync                      # or: pip install mcp
python server.py             # serves MCP at http://127.0.0.1:8900/mcp

curl -s http://127.0.0.1:8900/healthz            # -> {"ok": true}
python smoke_test.py http://127.0.0.1:8900/mcp   # lists tools, runs the job, downloads a file
```

## `server.py`

```python
--8<-- "example-mcp-server/server.py"
```

## `smoke_test.py`

```python
--8<-- "example-mcp-server/smoke_test.py"
```

## Deploy templates

`deploy/cloudflared.config.example.yml` (tunnel ingress):

```yaml
--8<-- "example-mcp-server/deploy/cloudflared.config.example.yml"
```

systemd user units — `deploy/example-mcp.service` and `deploy/cloudflared-example-mcp.service`:

```ini
--8<-- "example-mcp-server/deploy/example-mcp.service"
```

```ini
--8<-- "example-mcp-server/deploy/cloudflared-example-mcp.service"
```
