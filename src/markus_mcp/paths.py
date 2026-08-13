from __future__ import annotations

import os
from pathlib import Path


def markus_home() -> Path:
    """Per-user Markus home directory (not the git checkout)."""
    configured = os.getenv("MARKUS_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".markus").resolve()


def data_dir() -> Path:
    configured = os.getenv("MARKUS_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return markus_home() / "data"


def host_data_dir() -> Path:
    """Path shown to humans for screenshots/artifacts (defaults to data_dir)."""
    configured = os.getenv("MARKUS_HOST_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return data_dir()


def credentials_file() -> Path:
    configured = os.getenv("SAGA_CREDENTIALS_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # Always the per-user home file. Do not pick up a checkout's private.data via cwd.
    return markus_home() / "private.data"


def screenshot_dir() -> Path:
    return data_dir() / "screenshots"


def ensure_markus_dirs() -> dict[str, str]:
    home = markus_home()
    data = data_dir()
    shots = screenshot_dir()
    home.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    (data / "whatsapp-session").mkdir(parents=True, exist_ok=True)
    (data / "saga-session").mkdir(parents=True, exist_ok=True)
    (data / "saga").mkdir(parents=True, exist_ok=True)
    (data / "smartbill-session").mkdir(parents=True, exist_ok=True)
    (data / "smartbill").mkdir(parents=True, exist_ok=True)
    return {
        "markus_home": str(home),
        "data_dir": str(data),
        "screenshot_dir": str(shots),
        "credentials_file": str(credentials_file()),
    }
