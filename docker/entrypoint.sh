#!/bin/sh
# BadmintonGPT gateway entrypoint.
# Installs the committed nanobot config + agent brain into $HOME/.nanobot (runtime
# state in sessions/ and memory/ is preserved by the nanobot_state volume), links
# this repo's skill playbooks into the workspace, then execs `nanobot <cmd>`.
set -e

NB="$HOME/.nanobot"
WS="$NB/workspace"
mkdir -p "$WS/skills"

# Config + brain templates always win (so repo edits propagate on rebuild+restart);
# sessions/ and memory/ live alongside and persist via the named volume.
cp /app/nanobot/config.json "$NB/config.json"
for f in SOUL AGENTS USER HEARTBEAT; do
    [ -f "/app/nanobot/workspace/$f.md" ] && cp "/app/nanobot/workspace/$f.md" "$WS/$f.md"
done

# Skill playbooks are baked into the image at /app/skills; surface them to nanobot.
for s in badminton-db badminton-reels long-mcp-job; do
    ln -sfn "/app/skills/$s" "$WS/skills/$s"
done

# The DB lives in the separate badminton-db container now; the gateway reaches it over
# HTTP (http://badminton-db:8801/mcp) and never opens the SQLite file itself.

exec nanobot "$@"
