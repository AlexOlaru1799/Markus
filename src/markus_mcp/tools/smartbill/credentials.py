from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from markus_mcp.credentials_store import is_configured, read_values
from markus_mcp.paths import credentials_file


@dataclass(frozen=True)
class SmartbillCredentials:
    """SmartBill credentials from private.data.

    ``username`` falls back to ``saga_username``. Cloud UI password falls back to
    ``saga_password`` when ``smartbill_password`` is empty.
    """

    username: str
    token: str
    cif: str
    password: str
    source_file: str
    token_configured: bool
    username_configured: bool
    cif_configured: bool
    password_configured: bool


def credentials_path() -> Path:
    return credentials_file()


def load_credentials() -> SmartbillCredentials:
    path = credentials_path()
    values = read_values(path) if path.exists() else {}
    token = values.get("smartbill_token", "").strip()
    username = values.get("smartbill_username", "").strip() or values.get("saga_username", "").strip()
    cif = values.get("smartbill_cif", "").strip()
    password = values.get("smartbill_password", "").strip() or values.get("saga_password", "").strip()
    return SmartbillCredentials(
        username=username,
        token=token,
        cif=cif,
        password=password,
        source_file=str(path),
        token_configured=is_configured({"smartbill_token": token}, "smartbill_token"),
        username_configured=bool(username),
        cif_configured=bool(cif),
        password_configured=bool(password),
    )
