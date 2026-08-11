from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SagaCredentials:
    username: str
    password: str
    source_file: str


def credentials_path() -> Path:
    configured = os.getenv("SAGA_CREDENTIALS_FILE", "").strip()
    if configured:
        return Path(configured)

    # Host-friendly fallbacks for local runs outside Docker.
    for candidate in (
        Path("/app/private.data"),
        Path.cwd() / "private.data",
        Path(__file__).resolve().parents[4] / "private.data",
    ):
        if candidate.exists():
            return candidate
    return Path("/app/private.data")


def load_credentials() -> SagaCredentials:
    path = credentials_path()
    if not path.exists():
        raise FileNotFoundError(
            f"SAGA credentials file not found at {path}. "
            "Create private.data with username on line 1 and password on line 2."
        )

    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(
            f"SAGA credentials file {path} must contain username on line 1 and password on line 2."
        )

    return SagaCredentials(username=lines[0], password=lines[1], source_file=str(path))
