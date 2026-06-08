# syntax=docker/dockerfile:1
#
# example-mcp — self-contained reference MCP container (Streamable HTTP).
# The teaching demo for the Remote MCP Server Guide. Build context = this directory.
#
#   serve (default):  CMD python server.py  -> streamable-http MCP at :8900/mcp
#
# NOTE: MCP_HOST defaults to 0.0.0.0 here (not 127.0.0.1) so the server is reachable
# from outside the container (compose net / `docker run -p`). The app has NO auth;
# Cloudflare Access is the boundary when deployed — a plain `docker run` is unauthenticated.
#
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Only dependency: the official MCP SDK (FastMCP + client). It pulls in
# starlette/uvicorn/httpx, so nothing else is needed at runtime.
RUN uv pip install --system --no-cache "mcp>=1.0"

WORKDIR /app
COPY server.py pyproject.toml /app/

# Non-root (uid 1000, matching the other images); OUTPUT_DIR holds rendered files.
RUN useradd -m -u 1000 -s /bin/bash app && \
    mkdir -p /tmp/example-mcp-files && chown -R app:app /app /tmp/example-mcp-files
USER app

# MCP_HOST=0.0.0.0 so the port is reachable from the host / compose network.
ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8900 \
    OUTPUT_DIR=/tmp/example-mcp-files

EXPOSE 8900
# Liveness probe via stdlib urllib (no curl in the slim image). /healthz needs no state.
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8900/healthz', timeout=3).status==200 else 1)"

CMD ["python", "server.py"]
