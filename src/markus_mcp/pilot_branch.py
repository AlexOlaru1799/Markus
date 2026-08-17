"""Accountant-pilot git branch names: ap/<name>."""

from __future__ import annotations

import re

PILOT_BRANCH_PREFIX = "ap/"
_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def is_accountant_pilot_branch(branch: str) -> bool:
    """True for ap/<name> with a single path segment as the name."""
    name = (branch or "").strip()
    if not name or name in {"main", "master"}:
        return False
    if not name.startswith(PILOT_BRANCH_PREFIX):
        return False
    slug = name[len(PILOT_BRANCH_PREFIX) :]
    if not slug or "/" in slug or slug in {".", ".."}:
        return False
    return bool(_SLUG.fullmatch(slug))
