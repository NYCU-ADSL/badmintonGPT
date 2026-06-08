# syntax=docker/dockerfile:1
#
# badminton-db — self-contained MCP container (read-only SQLite over the badminton DB)
# + the DB-build step (ingest.py). No badminton-reels dependency: the parsing/models
# it needs are vendored under ingest_lib/. Build context = this directory (mcps/badminton-db/).
#
#   serve  (default):  CMD python3 /app/server.py   -> streamable-http MCP at :8801/mcp
#   ingest (one-shot):  override entrypoint -> python3 /app/ingest.py   (writes /app/data/badminton.db)
#
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Runtime deps: mcp (FastMCP + streamable-http server), and the DB-build libs
# (huggingface_hub/pydantic/python-dotenv used only by ingest.py / ingest_lib).
RUN uv pip install --system --no-cache \
    "mcp>=1.0" "huggingface_hub>=0.20" "pydantic>=2.0" "python-dotenv>=1.0"

WORKDIR /app
COPY . /app

# Non-root (uid 1000, matching the other images); /app/data is the DB mount point.
RUN useradd -m -u 1000 -s /bin/bash app && \
    mkdir -p /app/data && chown -R app:app /app
USER app

ENV BADMINTON_DB=/app/data/badminton.db \
    BADMINTON_HF_DIR=/app/data/hf_cache \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8801 \
    MCP_TRANSPORT=streamable-http

EXPOSE 8801
# Liveness probe via stdlib urllib (no curl in the slim image). /healthz needs no DB.
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=10s \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8801/healthz', timeout=3).status==200 else 1)"

CMD ["python3", "/app/server.py"]
