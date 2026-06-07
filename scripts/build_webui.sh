#!/usr/bin/env bash
# Rebuild the patched nanobot WebUI (progress-bar fork).
#
# Source clone: /mnt/ssd1/howchien/nanobot-webui  (HKUDS/nanobot @ v0.2.1
# + patches/webui-progress.patch applied). To recreate the clone from scratch:
#   git clone --depth 1 --branch v0.2.1 https://github.com/HKUDS/nanobot \
#       /mnt/ssd1/howchien/nanobot-webui
#   git -C /mnt/ssd1/howchien/nanobot-webui apply \
#       "$(dirname "$0")/../patches/webui-progress.patch"
set -euo pipefail

CLONE="${NANOBOT_WEBUI_SRC:-/mnt/ssd1/howchien/nanobot-webui}"
export PATH="$HOME/.bun/bin:$PATH"

[ -d "$CLONE/webui" ] || { echo "ERROR: clone not found at $CLONE (see header)"; exit 1; }
command -v bun >/dev/null || { echo "ERROR: bun not installed (curl -fsSL https://bun.sh/install | bash)"; exit 1; }

cd "$CLONE/webui"
bun install
bun run build   # outputs to $CLONE/nanobot/web/dist
echo "OK: built $CLONE/nanobot/web/dist"
