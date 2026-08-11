#!/bin/bash
# FootageGrab native host installer for macOS.
#
#   ./install/install.sh              # install for the default extension ID
#   ./install/install.sh --id <id>    # use a custom extension ID
#
# Registers the native messaging host with every Chromium-based browser found
# (Chrome, Brave, Chromium, Edge, Arc). Safe to re-run any time — e.g. after
# moving this folder.
set -euo pipefail

EXT_ID="lklbfpaopllmcbehfahbapehpadmlnel"  # fixed by the "key" in manifest.json
if [[ "${1:-}" == "--id" && -n "${2:-}" ]]; then
  EXT_ID="$2"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
HOST_ENTRY="$REPO_DIR/host/footagegrab_host.py"
APP_HOME="$HOME/Library/Application Support/FootageGrab"
LAUNCHER="$APP_HOME/bin/footagegrab-host"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

bold "FootageGrab installer"

# 1. python3
PYTHON3="$(command -v python3 || true)"
if [[ -z "$PYTHON3" ]]; then
  echo "python3 not found. Install Xcode Command Line Tools or Homebrew python first." >&2
  exit 1
fi
ok "python3: $PYTHON3"

# 2. yt-dlp / ffmpeg (warn only — the host reports these in the popup too)
for tool in yt-dlp ffmpeg; do
  found=""
  for p in /opt/homebrew/bin /usr/local/bin /opt/local/bin; do
    [[ -x "$p/$tool" ]] && found="$p/$tool" && break
  done
  [[ -z "$found" ]] && found="$(command -v "$tool" || true)"
  if [[ -n "$found" ]]; then
    ok "$tool: $found"
  else
    warn "$tool not found — install with: brew install $tool"
  fi
done

# 3. launcher script (absolute paths baked in; re-run install.sh if repo moves)
mkdir -p "$APP_HOME/bin" "$APP_HOME/logs"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
exec "$PYTHON3" "$HOST_ENTRY"
EOF
chmod +x "$LAUNCHER"
ok "launcher: $LAUNCHER"

# 4. native messaging manifests for every installed browser
MANIFEST_JSON="$(sed -e "s|__LAUNCHER__|$LAUNCHER|" -e "s|__EXT_ID__|$EXT_ID|" \
  "$SCRIPT_DIR/com.footagegrab.host.json.tpl")"

declare -a BROWSER_DIRS=(
  "Google/Chrome"
  "BraveSoftware/Brave-Browser"
  "Chromium"
  "Microsoft Edge"
  "Arc/User Data"
)
installed_any=0
for rel in "${BROWSER_DIRS[@]}"; do
  base="$HOME/Library/Application Support/$rel"
  [[ -d "$base" ]] || continue
  mkdir -p "$base/NativeMessagingHosts"
  printf '%s\n' "$MANIFEST_JSON" > "$base/NativeMessagingHosts/com.footagegrab.host.json"
  ok "registered with ${rel%%/*}"
  installed_any=1
done
if [[ "$installed_any" == 0 ]]; then
  warn "no Chromium-based browser profile folders found — open Chrome once, then re-run"
fi

# 5. self-test: spawn the host through the launcher, speak native messaging
echo
bold "Self-test"
if "$PYTHON3" "$REPO_DIR/host/selftest.py" --roundtrip "$LAUNCHER"; then
  echo
  bold "Done. Next steps:"
  cat <<STEPS
  1. Open chrome://extensions (or brave://extensions), enable Developer mode
  2. "Load unpacked" -> select: $REPO_DIR/extension
     (the extension ID must be $EXT_ID — it is pinned by the manifest key)
  3. Fully restart the browser (Cmd+Q) so it picks up the host manifest
  4. Open a YouTube video, press I then O then G
STEPS
else
  echo
  warn "self-test failed — check $APP_HOME/logs/host.log"
  exit 1
fi
