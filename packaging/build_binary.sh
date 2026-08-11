#!/usr/bin/env bash
# Build a closed markus-mcp binary with PyInstaller (macOS/Linux).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# System/Homebrew Pythons are unreliable here (pyexpat vs libexpat mismatch breaks
# plistlib and platform.mac_ver), so build from the project venv.
UV="$(command -v uv || true)"
[[ -z "$UV" && -x "$HOME/.local/bin/uv" ]] && UV="$HOME/.local/bin/uv"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
  if [[ -z "$UV" ]]; then
    echo "No .venv and no uv. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi
  "$UV" venv --python 3.12 "$ROOT/.venv"
  PYTHON="$ROOT/.venv/bin/python"
fi

install_deps() {
  if "$PYTHON" -m pip --version >/dev/null 2>&1; then
    "$PYTHON" -m pip install -e ".[packaging]"
  elif [[ -n "$UV" ]]; then
    "$UV" pip install --python "$PYTHON" -e ".[packaging]"
  else
    echo "Neither pip nor uv is available for $PYTHON" >&2
    exit 1
  fi
}

"$PYTHON" -c "import PyInstaller" >/dev/null 2>&1 || install_deps
"$PYTHON" -m playwright install chromium
"$PYTHON" -m PyInstaller packaging/markus-mcp.spec \
  --noconfirm --clean --distpath packaging/dist --workpath packaging/build

BIN="$ROOT/packaging/dist/markus-mcp"
if [[ ! -x "$BIN" ]]; then
  echo "Binary not found at $BIN" >&2
  exit 1
fi
echo "Built: $BIN"
echo "Next: packaging/macos/make_dmg.sh  OR  $BIN --setup --register-cursor"
