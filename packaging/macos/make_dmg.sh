#!/usr/bin/env bash
# Create Markus-.dmg from packaging/dist/markus-mcp
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi
VERSION="$(PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PY" -c \
  "from markus_mcp import __version__; print(__version__)" 2>/dev/null || true)"
if [[ -z "$VERSION" ]]; then
  VERSION="$(awk -F'"' '/^__version__/{print $2}' "$ROOT/src/markus_mcp/__init__.py")"
fi
BIN="$ROOT/packaging/dist/markus-mcp"
STAGE="$ROOT/packaging/dist/dmg-stage"
DMG="$ROOT/packaging/dist/Markus-${VERSION}-macos.dmg"

if [[ ! -x "$BIN" ]]; then
  echo "Build the binary first: packaging/build_binary.sh" >&2
  exit 1
fi

rm -rf "$STAGE"
mkdir -p "$STAGE/Markus"
cp "$BIN" "$STAGE/Markus/markus-mcp"
chmod +x "$STAGE/Markus/markus-mcp"
xattr -cr "$STAGE/Markus/markus-mcp" 2>/dev/null || true
codesign --force --sign - "$STAGE/Markus/markus-mcp"
cp "$ROOT/packaging/macos/Install Markus.command" "$STAGE/Markus/Install Markus.command"
chmod +x "$STAGE/Markus/Install Markus.command"

cat > "$STAGE/Markus/README.txt" <<EOF
Markus MCP ${VERSION}

1. Double-click "Install Markus.command"
2. Enter your SAGA email and password when prompted
3. Optionally enter your SmartBill API token (Contul Meu > Integrari)
4. Restart Cursor and reload MCP servers
5. Ask the agent: health_check
6. Pair WhatsApp via whatsapp_web_pair

To change credentials later, edit ~/.markus/private.data:
  saga_username = 'you@example.com'
  saga_password = 'your-password'
  smartbill_token = 'your-api-token'

No source code or Docker required.
EOF

rm -f "$DMG"
hdiutil create -volname "Markus ${VERSION}" -srcfolder "$STAGE/Markus" -ov -format UDZO "$DMG"
echo "Created $DMG"
