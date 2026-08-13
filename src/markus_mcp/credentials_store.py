"""Read and write ``private.data`` as ``key = value`` pairs.

Files written before this format existed hold the SAGA username on line 1 and the password
on line 2; those are still parsed so existing installs keep working without a rewrite.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

PLACEHOLDERS = {"", "your-saga-email@example.com", "your-saga-password"}

HEADER = (
    "# Markus credentials - keep this file private, never commit it.\n"
    "# One `key = value` per line; blank lines separate services.\n"
)

# Order used when rewriting the file, so generated files stay readable.
KEY_ORDER = (
    "saga_username",
    "saga_password",
    "smartbill_username",
    "smartbill_password",
    "smartbill_token",
    "smartbill_cif",
)

# Every file Markus writes contains at least one of these; add new keys here as services grow.
KNOWN_KEYS = frozenset(KEY_ORDER)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        quote = value[0]
        return value[1:-1].replace("\\" + quote, quote)
    return value


def _quote(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "'" + value.replace("'", "\\'") + "'"


def _assignments(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and KEY_RE.match(key.strip()):
            values[key.strip().lower()] = _unquote(value)
    return values


def parse(text: str) -> dict[str, str]:
    """Parse ``key = value`` lines, falling back to the legacy positional layout.

    The format is decided per file, not per line: a legacy password such as ``secret=x``
    would otherwise be mistaken for an assignment. Any file Markus writes contains at least
    one known key, so their absence means the file predates this format.
    """
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]

    values = _assignments(lines)
    if KNOWN_KEYS & values.keys():
        return values

    legacy: dict[str, str] = {}
    if lines:
        legacy["saga_username"] = lines[0]
    if len(lines) > 1:
        legacy["saga_password"] = lines[1]
    return legacy


def format_values(values: dict[str, str]) -> str:
    ordered = [k for k in KEY_ORDER if k in values]
    ordered += sorted(k for k in values if k not in KEY_ORDER)

    out = [HEADER]
    group = None
    for key in ordered:
        prefix = key.split("_", 1)[0]
        if group is not None and prefix != group:
            out.append("\n")
        group = prefix
        out.append(f"{key} = {_quote(values[key])}\n")
    return "".join(out)


def read_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return parse(path.read_text(encoding="utf-8"))


def write_values(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_values(values), encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def update_values(path: Path, updates: dict[str, str]) -> dict[str, str]:
    """Merge ``updates`` into the file, preserving any keys already stored."""
    values = read_values(path)
    values.update(updates)
    write_values(path, values)
    return values


def is_configured(values: dict[str, str], *keys: str) -> bool:
    return all(values.get(key, "").strip() not in PLACEHOLDERS for key in keys)


def parse_assignments(text: str) -> dict[str, str]:
    """Parse ``key=value`` lines fed on stdin, keeping values byte-exact.

    Values are never unquoted or stripped here: a password may legitimately contain quotes,
    spaces or ``=``. Splitting on the first ``=`` is unambiguous because the caller controls
    the key names.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not KEY_RE.match(key.strip()):
            continue
        values[key.strip().lower()] = value
    return values
