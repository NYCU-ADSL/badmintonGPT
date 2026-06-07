#!/usr/bin/env bash
# Deploy the patched WebUI build over the installed nanobot-ai dist.
#
# NOTE: `uv tool upgrade nanobot-ai` wipes the install dir — re-run this script
# afterwards (and rebase patches/webui-progress.patch if the version changed).
set -euo pipefail

CLONE="${NANOBOT_WEBUI_SRC:-/mnt/ssd1/howchien/nanobot-webui}"
PINNED_VERSION="0.2.1"

PKG=$(ls -d "$HOME"/.local/share/uv/tools/nanobot-ai/lib/python3.*/site-packages/nanobot 2>/dev/null | head -1)
[ -n "$PKG" ] || { echo "ERROR: installed nanobot package not found"; exit 1; }

INSTALLED=$(ls -d "$PKG"/../nanobot_ai-*.dist-info 2>/dev/null | sed -E 's/.*nanobot_ai-([0-9.]+)\.dist-info/\1/' | head -1)
if [ "$INSTALLED" != "$PINNED_VERSION" ]; then
  echo "ERROR: installed nanobot-ai is $INSTALLED, patch built for $PINNED_VERSION."
  echo "Rebase patches/webui-progress.patch onto the new tag, rebuild, then update PINNED_VERSION."
  exit 1
fi

SRC="$CLONE/nanobot/web/dist"
DST="$PKG/web/dist"
[ -f "$SRC/index.html" ] || { echo "ERROR: no build at $SRC (run scripts/build_webui.sh first)"; exit 1; }

# one-time backup of the original shipped dist
[ -d "$DST.orig" ] || cp -a "$DST" "$DST.orig"

rsync -a --delete "$SRC/" "$DST/"
echo "OK: deployed $(grep -o 'index-[A-Za-z0-9_-]*\.js' "$DST/index.html" | head -1) -> $DST"
echo "Reload the WebUI with a hard refresh (asset hashes changed)."
