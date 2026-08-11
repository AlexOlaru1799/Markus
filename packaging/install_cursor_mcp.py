"""CLI wrapper; prefers in-package cursor_install when available."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from a checkout without install: python packaging/install_cursor_mcp.py
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from markus_mcp.cursor_install import merge_markus_mcp  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register Markus MCP in Cursor mcp.json")
    parser.add_argument("--binary", required=True, help="Path to markus-mcp executable")
    parser.add_argument("--mcp-json", default="", help="Override Cursor mcp.json path")
    args = parser.parse_args(argv)
    try:
        result = merge_markus_mcp(
            binary=Path(args.binary),
            mcp_json=Path(args.mcp_json) if args.mcp_json else None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Updated {result['mcp_json']}")
    print(f"Markus home: {result['markus_home']}")
    print("Reload MCP servers in Cursor, then ask for health_check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
