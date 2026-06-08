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

## Run it in a container (Docker)

The example also ships a `Dockerfile` and a standalone `docker-compose.yml` — an alternative to
running it under systemd (see the [Guide](index.md#4b-or-run-it-in-a-container-docker)):

```bash
docker build -t example-mcp .
docker run --rm -p 8900:8900 example-mcp         # MCP at http://localhost:8900/mcp
# or: docker compose up --build

curl -s http://localhost:8900/healthz            # -> {"ok": true}
python smoke_test.py http://localhost:8900/mcp
```

The image sets `MCP_HOST=0.0.0.0` (so the published port is reachable from outside the container),
declares a `HEALTHCHECK` on `GET /healthz`, and uses `OUTPUT_DIR` for job artifacts. Set
`PUBLIC_BASE_URL` at run time so the file URLs point at your public origin. There is no app-level
auth — front it with **Cloudflare Tunnel + Access** for the remote/auth boundary, exactly as the
systemd path does.

### `Dockerfile`

```dockerfile
--8<-- "example-mcp-server/Dockerfile"
```

### `docker-compose.yml`

```yaml
--8<-- "example-mcp-server/docker-compose.yml"
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
