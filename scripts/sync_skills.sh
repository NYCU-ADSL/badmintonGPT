#!/usr/bin/env bash
# Copy this repo's skill playbooks into the nanobot workspace (host/dev mode).
#
# Skills must live *inside* ~/.nanobot/workspace — they must NOT be symlinked in.
# nanobot's `restrictToWorkspace` boundary resolves symlinks before the containment
# check (security/workspace_policy.py:is_path_within -> Path.resolve()), so a
# symlinked skill dir resolves to its real path OUTSIDE the workspace and the agent's
# read_file is rejected with:
#   Path .../skills/<name>/SKILL.md is outside allowed directory ~/.nanobot/workspace
#   (this is a hard policy boundary, not a transient failure ...)
# Copying the dirs keeps them in-bounds. Re-run after editing any skills/* and then
# restart the gateway (see CLAUDE.md "When editing nanobot behavior").
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS="${NANOBOT_WORKSPACE:-$HOME/.nanobot/workspace}"
mkdir -p "$WS/skills"

# Enumerate every skill dir under skills/ (don't hardcode names) so a newly added skill
# is synced automatically without editing this loop.
for d in "$REPO"/skills/*/; do
    s="$(basename "$d")"
    rm -rf "$WS/skills/$s"          # also clears a stale symlink from older setups
    cp -r "$d" "$WS/skills/$s"
    echo "synced skill: $WS/skills/$s"
done

# The repo is the only source of skills: move runtime-written ones (built-in
# skill-creator) out of the workspace so they cannot override the repo playbooks.
# Moved, not deleted, so they are recoverable from $NB/skills-pruned/.
NB="$(dirname "$WS")"
for d in "$WS"/skills/*/; do
    [ -d "$d" ] || continue
    s="$(basename "$d")"
    if [ ! -d "$REPO/skills/$s" ]; then
        mkdir -p "$NB/skills-pruned"
        rm -rf "$NB/skills-pruned/$s"
        mv "$WS/skills/$s" "$NB/skills-pruned/$s"
        echo "pruned non-repo skill: $s -> $NB/skills-pruned/$s"
    fi
done
