"""Non-secret process fingerprint so agents can detect a stale MCP."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from markus_mcp import __version__

STARTED_AT = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def source_revision() -> str:
    root = repo_root()
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return (completed.stdout or "").strip() or "unknown"


def fingerprint() -> dict[str, str]:
    return {
        "version": __version__,
        "source_revision": source_revision(),
        "started_at": STARTED_AT,
        "pid": str(os.getpid()),
    }
