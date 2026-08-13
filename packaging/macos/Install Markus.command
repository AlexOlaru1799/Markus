#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Must not contain spaces: Cursor's MCP spawn splits the command path on whitespace
# (ENOENT on ".../Library/Application" if installed under Application Support).
TARGET_DIR="$HOME/.markus/bin"
APP="$TARGET_DIR/markus-mcp"
CREDS_FILE="$HOME/.markus/private.data"

ask() {
  # $1 = prompt, $2 = "hidden" to mask input. Cancel / error → empty string.
  # Prompt is passed as argv so AppleScript quoting cannot drop the answer.
  local prompt="$1"
  local hidden="${2:-}"
  if [[ "$hidden" == "hidden" ]]; then
    osascript - "$prompt" <<'APPLESCRIPT' 2>/dev/null || true
on run argv
  set thePrompt to item 1 of argv
  try
    set dlg to display dialog thePrompt default answer "" buttons {"Cancel", "OK"} default button "OK" with title "Markus setup" with hidden answer
    return text returned of dlg
  on error
    return ""
  end try
end run
APPLESCRIPT
  else
    osascript - "$prompt" <<'APPLESCRIPT' 2>/dev/null || true
on run argv
  set thePrompt to item 1 of argv
  try
    set dlg to display dialog thePrompt default answer "" buttons {"Cancel", "OK"} default button "OK" with title "Markus setup"
    return text returned of dlg
  on error
    return ""
  end try
end run
APPLESCRIPT
  fi
}

echo "Installing Markus…"
mkdir -p "$TARGET_DIR"
cp "$DIR/markus-mcp" "$APP"
chmod +x "$APP"
# DMG copies inherit Gatekeeper provenance; unsigned/broken signature → Killed: 9.
xattr -cr "$APP" 2>/dev/null || true
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
codesign --force --sign - "$APP" 2>/dev/null || true

echo "Setting up Markus (may download a browser, about 150 MB, one time)…"
if ! "$APP" --setup; then
  echo "Full setup did not finish; retrying without downloading the browser…"
  if ! "$APP" --setup --skip-browser; then
    echo ""
    echo "macOS blocked markus-mcp (Killed: 9 / Gatekeeper)."
    echo "Open System Settings → Privacy & Security, allow markus-mcp, then run this installer again."
    read -r -p "Press Enter to close…" _
    exit 1
  fi
fi

SAGA_USER="$(ask 'SAGA email / username:')"
SAGA_PASS=""
if [[ -n "$SAGA_USER" ]]; then
  SAGA_PASS="$(ask 'SAGA password:' hidden)"
fi
SMARTBILL_TOKEN="$(ask 'SmartBill API token (optional):' hidden)"

# Pipe lines directly. Do not build CREDS via $(...) — command substitution
# strips trailing newlines and would glue smartbill_token onto saga_password.
if [[ -n "$SAGA_USER" && -n "$SAGA_PASS" ]] || [[ -n "$SMARTBILL_TOKEN" ]]; then
  if [[ -n "$SMARTBILL_TOKEN" ]]; then
    echo "SmartBill token entered — saving to ${CREDS_FILE}"
  else
    echo "SmartBill token skipped (empty). Add smartbill_token later in ${CREDS_FILE}"
  fi
  {
    if [[ -n "$SAGA_USER" && -n "$SAGA_PASS" ]]; then
      printf 'saga_username=%s\n' "$SAGA_USER"
      printf 'saga_password=%s\n' "$SAGA_PASS"
    fi
    if [[ -n "$SMARTBILL_TOKEN" ]]; then
      printf 'smartbill_token=%s\n' "$SMARTBILL_TOKEN"
    fi
  } | "$APP" --set-credentials
else
  echo "Skipped credentials. Add them later in ${CREDS_FILE}"
fi

echo ""
echo "Credentials file: ${CREDS_FILE}"
echo "Markus installed to: $APP"
echo "Restart Cursor, then ask the agent: health_check"
read -r -p "Press Enter to close…" _
