# syntax=docker/dockerfile:1
#
# BadmintonGPT gateway image.
#
# Builds our nanobot FORK from the in-repo vendor (vendor/nanobot/ = HKUDS/nanobot
# v0.2.1 tracked via git subtree + this repo's changes) so the served WebUI carries the
# customizations, then layers the embedded `util` stdio MCP (mcps/util/), skills, and the committed
# agent config/brain. badminton-db is now its OWN container (mcps/badminton-db/) reached
# over HTTP; reels is remote. The WebUI dist is bundled at install time by the vendored
# hatch build hook (NANOBOT_FORCE_WEBUI_BUILD=1). See docs/DEPLOY.md.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Node 20 — vendor/nanobot/hatch_build.py runs `npm install && npm run build` to bundle
# the Vite WebUI into nanobot/web/dist during the pip install below. tini = PID 1 reaper.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git tini && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# --- Install the vendored, patched nanobot (forces the WebUI rebuild) ---
COPY vendor/nanobot/ /opt/nanobot-src/
RUN cd /opt/nanobot-src && \
    NANOBOT_FORCE_WEBUI_BUILD=1 uv pip install --system --no-cache . && \
    nanobot --version

# --- Deps for the embedded `util` stdio MCP (mcp) + nanobot runtime extras ---
RUN uv pip install --system --no-cache \
    "mcp>=1.0" "pydantic>=2.0" \
    "python-dotenv>=1.0" "websockets>=12.0" "jsonschema>=4.0" "httpx>=0.27"

# --- This repo's code + agent config/brain templates ---
WORKDIR /app
COPY mcps/util/ mcps/util/
COPY skills/ skills/
COPY eval/ eval/
COPY nanobot/ nanobot/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

# Non-root (uid 1000, matching upstream); writable nanobot home + data mount point
RUN useradd -m -u 1000 -s /bin/bash nanobot && \
    mkdir -p /home/nanobot/.nanobot /app/data && \
    chown -R nanobot:nanobot /home/nanobot /app
USER nanobot
ENV HOME=/home/nanobot \
    BADMINTON_DB=/app/data/badminton.db

# 8765 = WebUI + WebSocket (cloudflared target); 18790 = gateway /health (in-container)
EXPOSE 8765 18790
ENTRYPOINT ["tini", "--", "entrypoint.sh"]
CMD ["gateway"]
