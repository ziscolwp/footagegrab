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

# 3. PO token sidecar + yt-dlp plugin (best-effort: without it grabs still
#    work, YouTube just degrades some player clients to lower quality).
#    Pinned release — bump POT_VERSION and re-run this script to update.
POT_VERSION="v0.8.1"
POT_BIN="$APP_HOME/bin/bgutil-pot"
POT_BASE="https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/download/$POT_VERSION"
PLUGIN_DIR="$HOME/.config/yt-dlp/plugins/bgutil-ytdlp-pot-provider"
case "$(uname -m)" in
  arm64|aarch64) POT_ASSET="bgutil-pot-macos-aarch64" ;;
  *)             POT_ASSET="bgutil-pot-macos-x86_64" ;;
esac
mkdir -p "$APP_HOME/bin"
if [[ -x "$POT_BIN" && -d "$PLUGIN_DIR" \
      && "$(cat "$POT_BIN.version" 2>/dev/null)" == "$POT_VERSION" ]]; then
  ok "PO token sidecar: $POT_VERSION (already installed)"
elif curl -fsSL --retry 2 -o "$POT_BIN.tmp" "$POT_BASE/$POT_ASSET" \
     && curl -fsSL --retry 2 -o "$POT_BIN.plugin.zip" "$POT_BASE/bgutil-ytdlp-pot-provider-rs.zip"; then
  mv "$POT_BIN.tmp" "$POT_BIN"
  chmod +x "$POT_BIN"
  rm -rf "$PLUGIN_DIR"
  mkdir -p "$PLUGIN_DIR"
  if unzip -oq "$POT_BIN.plugin.zip" -d "$PLUGIN_DIR"; then
    printf '%s' "$POT_VERSION" > "$POT_BIN.version"
    ok "PO token sidecar: $POT_VERSION -> $POT_BIN"
    ok "yt-dlp POT plugin: $PLUGIN_DIR"
  else
    warn "could not extract the POT plugin — grabs degrade to tokenless"
  fi
  rm -f "$POT_BIN.plugin.zip"
else
  rm -f "$POT_BIN.tmp" "$POT_BIN.plugin.zip"
  warn "could not download the PO token sidecar — grabs degrade to tokenless"
fi

# 4. launcher script (absolute paths baked in; re-run install.sh if repo moves)
mkdir -p "$APP_HOME/bin" "$APP_HOME/logs"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
exec "$PYTHON3" "$HOST_ENTRY"
EOF
chmod +x "$LAUNCHER"
ok "launcher: $LAUNCHER"

# 5. native messaging manifests for every installed browser
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

# 6. self-test: spawn the host through the launcher, speak native messaging
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
