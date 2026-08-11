#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Must not contain spaces: Cursor's MCP spawn splits the command path on whitespace
# (ENOENT on ".../Library/Application" if installed under Application Support).
TARGET_DIR="$HOME/.markus/bin"
APP="$TARGET_DIR/markus-mcp"

ask() {
  # $1 = prompt, $2 = "hidden" to mask input. Cancel yields an empty string.
  local hidden=""
  [[ "${2:-}" == "hidden" ]] && hidden="with hidden answer"
  osascript \
    -e "display dialog \"$1\" default answer \"\" buttons {\"Cancel\",\"OK\"} default button \"OK\" with title \"Markus setup\" $hidden" \
    -e 'text returned of result' 2>/dev/null || true
}

echo "Installing Markus…"
mkdir -p "$TARGET_DIR"
cp "$DIR/markus-mcp" "$APP"
chmod +x "$APP"
# The binary is unsigned, so Gatekeeper blocks it once it carries the download quarantine flag.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Downloading the browser Markus uses (about 150 MB, one time)…"
if ! "$APP" --setup; then
  echo ""
  echo "Setup did not finish. Check your internet connection and run this installer again."
  read -r -p "Press Enter to close…" _
  exit 1
fi

SAGA_USER="$(ask 'SAGA email / username:')"
SAGA_PASS=""
if [[ -n "$SAGA_USER" ]]; then
  SAGA_PASS="$(ask 'SAGA password:' hidden)"
fi

if [[ -n "$SAGA_USER" && -n "$SAGA_PASS" ]]; then
  # Passed on stdin so the password never appears in the process list.
  printf 'saga_username=%s\nsaga_password=%s\n' "$SAGA_USER" "$SAGA_PASS" | "$APP" --set-credentials
else
  echo "Skipped credentials. Add them later in $HOME/.markus/private.data"
fi

echo ""
echo "Markus installed to: $APP"
echo "Restart Cursor, then ask the agent: health_check"
read -r -p "Press Enter to close…" _
