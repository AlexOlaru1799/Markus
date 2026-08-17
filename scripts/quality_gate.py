#!/usr/bin/env python3
"""Offline regression gate used by agents and CI. No live SAGA."""

from __future__ import annotations

import compileall
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CORE_TOOLS = (
    "health_check",
    "list_tools",
    "saga_login",
    "saga_add_iesire",
    "saga_add_intrare",
    "saga_post_bank_entries",
    "saga_wipe_data",
    "smartbill_invoices_to_saga_xml",
)


def _fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def check_compile() -> int:
    ok = compileall.compile_dir(str(SRC / "markus_mcp"), quiet=1)
    return 0 if ok else _fail("compileall failed")


def check_import() -> int:
    from markus_mcp.server import mcp  # noqa: F401
    from markus_mcp.tools.catalog import TOOL_CATALOG
    from markus_mcp.tools.health import health_check

    names = {item.name for item in TOOL_CATALOG}
    missing = [name for name in CORE_TOOLS if name not in names]
    if missing:
        return _fail(f"catalog missing tools: {', '.join(missing)}")
    if len(TOOL_CATALOG) < 60:
        return _fail(f"catalog too small: {len(TOOL_CATALOG)}")
    payload = health_check()
    if payload.get("status") != "ok":
        return _fail("health_check status is not ok")
    if "source_revision" not in payload or "started_at" not in payload:
        return _fail("health_check missing source fingerprint")
    return 0


def check_tests() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"],
        cwd=ROOT,
        env=env,
    )
    return 0 if completed.returncode == 0 else _fail("unittest failed")


PLACEHOLDERS = ("your-password", "your-saga", "example", "replace_with", "***", "placeholder")


def check_secrets() -> int:
    from markus_mcp.sanitize import is_forbidden_path, secret_assignment_lines

    completed = subprocess.run(
        ["git", "status", "--porcelain", "-u"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    for line in completed.stdout.splitlines():
        path = line[3:].strip()
        if not path or path.startswith("src/") or path.startswith("tests/"):
            if path and is_forbidden_path(path):
                return _fail(f"forbidden path in working tree: {path}")
            continue
        if is_forbidden_path(path):
            return _fail(f"forbidden path in working tree: {path}")
        full = ROOT / path
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except OSError:
            continue
        for hit in secret_assignment_lines(text):
            lowered = hit.casefold()
            if any(token in lowered for token in PLACEHOLDERS):
                continue
            if re.search(r"[=:]\s*['\"]?.{8,}", hit):
                return _fail(f"possible secret assignment in {path}")
    return 0


def main() -> int:
    for step in (check_compile, check_import, check_tests, check_secrets):
        code = step()
        if code:
            return code
    print("quality_gate: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
