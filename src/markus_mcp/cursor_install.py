"""Register Markus in Cursor mcp.json (used by installers and --register-cursor)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from markus_mcp.cursor_skills import install_cursor_skills
from markus_mcp.paths import ensure_markus_dirs, markus_home


def cursor_mcp_json_path() -> Path:
    override = os.getenv("CURSOR_MCP_JSON", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".cursor" / "mcp.json").resolve()


def current_binary_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    # Dev: prefer console script if on PATH later; for now use python -m style via sys.executable + -m
    return Path(sys.executable).resolve()


def build_markus_entry(*, binary: Path | None = None) -> dict:
    if binary is None:
        if getattr(sys, "frozen", False):
            command = str(Path(sys.executable).resolve())
            args: list[str] = []
        else:
            command = str(Path(sys.executable).resolve())
            args = ["-m", "markus_mcp"]
    else:
        command = str(Path(binary).expanduser().resolve())
        args = []
    # Only the binary location is machine-specific enough to pin here. Home, data dir and
    # credentials are resolved from the running user's home at startup, so writing them would
    # freeze one machine's layout into a file that may be copied or synced to another.
    return {
        "command": command,
        "args": args,
        "env": {"MARKUS_MCP_TRANSPORT": "stdio"},
    }


def merge_markus_mcp(*, binary: Path | None = None, mcp_json: Path | None = None) -> dict:
    ensure_markus_dirs()
    mcp_path = mcp_json or cursor_mcp_json_path()
    entry = build_markus_entry(binary=binary)

    if mcp_path.exists():
        raw = json.loads(mcp_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{mcp_path} must contain a JSON object")
    else:
        raw = {}

    servers = raw.get("mcpServers")
    if servers is None:
        servers = {}
        raw["mcpServers"] = servers
    if not isinstance(servers, dict):
        raise ValueError(f"{mcp_path}: mcpServers must be an object")

    servers["markus"] = entry
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = mcp_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    tmp.replace(mcp_path)
    return {
        "ok": True,
        "mcp_json": str(mcp_path),
        "markus_home": str(markus_home()),
        "entry": entry,
        "skills": install_cursor_skills(),
    }
