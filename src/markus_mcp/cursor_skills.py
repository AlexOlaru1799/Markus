"""Install Markus agent skills into the user's Cursor skills folder."""

from __future__ import annotations

import os
from pathlib import Path


CLIENT_SKILLS = (
    "smartbill-to-saga-import",
    "export-smartbill-supplier-invoices",
    "import-xml-to-saga",
    "import-iesiri-xml-to-saga",
    "import-incasari-xml-to-saga",
    "import-fx-invoice-to-saga",
    "wipe-saga-data",
)


def bundled_skills_root() -> Path:
    return Path(__file__).resolve().parent / "agent_skills"


def cursor_skills_dir() -> Path:
    override = os.getenv("CURSOR_SKILLS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".cursor" / "skills").resolve()


def install_cursor_skills() -> dict:
    """Copy bundled client skills to ~/.cursor/skills (overwrites same-named skills)."""
    src_root = bundled_skills_root()
    dest_root = cursor_skills_dir()
    dest_root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    missing: list[str] = []
    for name in CLIENT_SKILLS:
        src = src_root / name / "SKILL.md"
        if not src.is_file():
            missing.append(name)
            continue
        dest = dest_root / name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        installed.append(str(dest))
    return {
        "ok": not missing,
        "skills_dir": str(dest_root),
        "installed": installed,
        "missing": missing,
    }
