#!/bin/sh
# BadmintonGPT gateway entrypoint.
# Installs the committed nanobot config + agent brain into $HOME/.nanobot (runtime
# state in sessions/ and memory/ is preserved by the nanobot_state volume), copies
# this repo's skill playbooks into the workspace, then execs `nanobot <cmd>`.
set -e

NB="$HOME/.nanobot"
WS="$NB/workspace"
mkdir -p "$WS/skills" "$WS/projects"

# Config + brain templates always win (so repo edits propagate on rebuild+restart);
# sessions/ and memory/ live alongside and persist via the named volume.
cp /app/nanobot/config.json "$NB/config.json"
for f in SOUL AGENTS USER HEARTBEAT; do
    [ -f "/app/nanobot/workspace/$f.md" ] && cp "/app/nanobot/workspace/$f.md" "$WS/$f.md"
done

# Skill playbooks are baked into the image at /app/skills; surface them to nanobot.
# COPY (don't symlink): nanobot's restrictToWorkspace boundary resolves symlinks, so a
# symlinked skill dir resolves to /app/skills/... (outside $WS) and the agent's read_file
# is rejected ("Path .../SKILL.md is outside allowed directory"). Copies stay in-bounds.
# rm -rf first so a stale symlink on the persisted nanobot_state volume is replaced (not
# copied through). Runs on every container start, so a rebuilt /app/skills propagates.
# Enumerate every skill dir under /app/skills (don't hardcode names) so a newly added
# skill is surfaced automatically without editing this loop.
for d in /app/skills/*/; do
    s="$(basename "$d")"
    rm -rf "$WS/skills/$s"
    cp -r "$d" "$WS/skills/$s"
done

# The repo is the only source of skills. Anything else in $WS/skills was written at
# runtime (the built-in skill-creator) and persists on the volume, where it silently
# overrides the repo playbooks for every user (e.g. an agent-written skill that made
# the agent re-verify every video-retrieval hit with a chain of badminton-db queries).
# Move such dirs out of the workspace (not delete) so they are recoverable.
for d in "$WS/skills"/*/; do
    [ -d "$d" ] || continue
    s="$(basename "$d")"
    if [ ! -d "/app/skills/$s" ]; then
        mkdir -p "$NB/skills-pruned"
        rm -rf "$NB/skills-pruned/$s"
        mv "$WS/skills/$s" "$NB/skills-pruned/$s"
        echo "entrypoint: pruned non-repo skill '$s' -> $NB/skills-pruned/$s"
    fi
done

# The DB lives in the separate badminton-db container now; the gateway reaches it over
# HTTP (http://badminton-db:8801/mcp) and never opens the SQLite file itself.

exec nanobot "$@"
