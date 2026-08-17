"""Redact secrets and refuse production-looking artifacts in Git."""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN_NAMES = frozenset(
    {
        "private.data",
        ".env",
        "credentials.json",
    }
)
FORBIDDEN_PATH_PARTS = (
    "saga-session",
    "whatsapp-session",
    "smartbill-session",
    "/.markus/",
    "\\.markus\\",
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(saga_password|smartbill_password|smartbill_token|password|passwd|api[_-]?key|secret)\s*[=:]\s*\S+"
)


def is_forbidden_path(path: str | Path) -> bool:
    text = str(path).replace("\\", "/")
    name = Path(text).name.casefold()
    if name in {item.casefold() for item in FORBIDDEN_NAMES}:
        return True
    lowered = text.casefold()
    return any(part.casefold() in lowered for part in FORBIDDEN_PATH_PARTS)


def secret_assignment_lines(text: str) -> list[str]:
    hits: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if SECRET_ASSIGNMENT.search(stripped):
            hits.append(stripped[:80])
    return hits


def sanitize_label(value: str) -> str:
    """Collapse a partner/CIF-looking string for scenario notes."""
    text = (value or "").strip()
    if not text:
        return "DEMO"
    if re.fullmatch(r"RO?\d{6,}", text.replace(" ", ""), flags=re.IGNORECASE):
        return "CIF-DEMO"
    return "DEMO"
