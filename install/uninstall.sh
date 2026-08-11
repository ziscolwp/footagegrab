#!/bin/bash
# Remove the FootageGrab native host registration.
#   ./install/uninstall.sh           # remove manifests + launcher, keep config/history
#   ./install/uninstall.sh --purge   # also remove config, history, and logs
set -euo pipefail

APP_HOME="$HOME/Library/Application Support/FootageGrab"

for rel in "Google/Chrome" "BraveSoftware/Brave-Browser" "Chromium" "Microsoft Edge" "Arc/User Data"; do
  f="$HOME/Library/Application Support/$rel/NativeMessagingHosts/com.footagegrab.host.json"
  if [[ -f "$f" ]]; then
    rm "$f"
    echo "removed: $f"
  fi
done

rm -f "$APP_HOME/bin/footagegrab-host"

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$APP_HOME"
  echo "purged: $APP_HOME"
else
  echo "kept config/history at: $APP_HOME (use --purge to remove)"
fi
echo "Remove the extension from chrome://extensions manually."
