from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from markus_mcp.credentials_store import is_configured, read_values
from markus_mcp.paths import credentials_file


@dataclass(frozen=True)
class SagaCredentials:
    username: str
    password: str
    source_file: str


def credentials_path() -> Path:
    return credentials_file()


def load_credentials() -> SagaCredentials:
    path = credentials_path()
    if not path.exists():
        raise FileNotFoundError(
            f"SAGA credentials file not found at {path}. Create it with:\n"
            "saga_username = 'you@example.com'\n"
            "saga_password = 'your-password'\n"
            "(or set SAGA_CREDENTIALS_FILE). Run: markus-mcp --setup"
        )

    values = read_values(path)
    if not is_configured(values, "saga_username", "saga_password"):
        raise ValueError(
            f"SAGA credentials are not set in {path}. Add:\n"
            "saga_username = 'you@example.com'\n"
            "saga_password = 'your-password'"
        )

    return SagaCredentials(
        username=values["saga_username"],
        password=values["saga_password"],
        source_file=str(path),
    )
