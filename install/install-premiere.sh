#!/bin/bash
# Install the FootageGrab Bridge CEP panel into Premiere Pro (macOS).
#
#   ./install/install-premiere.sh          # copy install (re-run after edits)
#   ./install/install-premiere.sh --link   # symlink install (dev: edits live)
#
# No admin rights needed — CEP extensions live in the user's home Library.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/../premiere" && pwd)"
DEST="$HOME/Library/Application Support/Adobe/CEP/extensions/FootageGrabBridge"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is for macOS." >&2
  exit 1
fi
if [ ! -f "$SRC/CSXS/manifest.xml" ]; then
  echo "premiere/CSXS/manifest.xml not found — run from the repo." >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"

if [ "${1:-}" = "--link" ]; then
  ln -s "$SRC" "$DEST"
  echo "Symlinked $DEST -> $SRC"
else
  mkdir -p "$DEST"
  cp -R "$SRC/CSXS" "$SRC/css" "$SRC/js" "$SRC/jsx" "$SRC/index.html" "$SRC/.debug" "$DEST/"
  echo "Copied panel to $DEST"
fi

# Unsigned CEP extensions need PlayerDebugMode. Premiere versions differ in
# which CSXS version they read — writing extras is harmless.
for CSXS_VERSION in 10 11 12; do
  defaults write "com.adobe.CSXS.$CSXS_VERSION" PlayerDebugMode 1 2>/dev/null || true
done
killall cfprefsd 2>/dev/null || true

# stale quarantine attributes would keep the panel from loading
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo ""
echo "FootageGrab Bridge installed."
echo "Restart Premiere Pro, then open Window > Extensions > FootageGrab Bridge."
