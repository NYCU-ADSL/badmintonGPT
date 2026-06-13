#!/usr/bin/env bash
# Guard for the vendored-nanobot patches.
#
# Verifies this repo's patches/*.patch still apply cleanly onto the pinned upstream
# nanobot tag. This protects the "Updating to a new upstream nanobot" recipe in
# vendor/README.md: if a patch is edited (or the pinned TAG below is bumped) and a
# patch stops applying, this fails loudly instead of letting the vendored tree drift
# silently from its documented provenance.
#
#   bash scripts/check_patches.sh
#
# Exit 0 = all patches apply; non-zero = at least one failed (details in output).
# Needs only git + network (clones the tag shallowly into a temp dir, cleaned on exit).
set -euo pipefail

REPO="https://github.com/HKUDS/nanobot"
TAG="v0.2.1"                       # keep in sync with vendor/README.md and the image tag
# Apply in the same order as vendor/README.md's recipe:
PATCHES=(webui-progress.patch mcp-probe-origin-aware.patch webui-trust-proxy-auth.patch
         webui-branding.patch reply-language.patch webui-thinking-animation.patch
         webui-boot-splash.patch webui-visualizer.patch webui-court-theme.patch)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATCH_DIR="$HERE/patches"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "→ cloning $REPO @ $TAG (shallow) …"
git clone --quiet --depth 1 --branch "$TAG" "$REPO" "$TMP/nanobot"
cd "$TMP/nanobot"

rc=0
for p in "${PATCHES[@]}"; do
  # --check first (dry run), then apply for real so a patch that depends on an
  # earlier one's context is still validated against the cumulative tree.
  if git apply --check "$PATCH_DIR/$p" && git apply "$PATCH_DIR/$p"; then
    echo "  ✓ $p applies"
  else
    echo "  ✗ $p FAILED to apply onto $TAG" >&2
    rc=1
  fi
done

if [ "$rc" -eq 0 ]; then
  echo "✓ all ${#PATCHES[@]} patches apply cleanly onto $TAG"
else
  echo "✗ one or more patches no longer apply — rebase them (see vendor/README.md §Updating) and re-export." >&2
fi
exit "$rc"
