#!/usr/bin/env python3
"""Green, batched publish to the current ap/<name> branch only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from markus_mcp.paths import markus_home  # noqa: E402
from markus_mcp.pilot_branch import PILOT_BRANCH_PREFIX, is_accountant_pilot_branch  # noqa: E402
from markus_mcp.sanitize import is_forbidden_path  # noqa: E402

CHECKPOINT_MIN_MINUTES = 120


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, check=check, capture_output=True, text=True)


def _fail(message: str) -> int:
    print(f"checkpoint refused: {message}", file=sys.stderr)
    return 1


def state_path() -> Path:
    return markus_home() / "accountant-pilot-state.json"


def load_state() -> dict:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_state(payload: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def branch_checkpoint_epoch(state: dict, branch: str) -> float:
    branches = state.get("branches")
    if isinstance(branches, dict):
        entry = branches.get(branch)
        if isinstance(entry, dict):
            return float(entry.get("last_checkpoint_epoch") or 0)
    if state.get("branch") == branch:
        return float(state.get("last_checkpoint_epoch") or 0)
    return 0.0


def record_checkpoint(branch: str) -> None:
    state = load_state()
    branches = state.get("branches")
    if not isinstance(branches, dict):
        branches = {}
        if state.get("branch") and state.get("last_checkpoint_epoch"):
            branches[str(state["branch"])] = {
                "last_checkpoint_epoch": state.get("last_checkpoint_epoch"),
                "last_checkpoint_at": state.get("last_checkpoint_at"),
            }
    now = time.time()
    iso = datetime.now(timezone.utc).isoformat()
    branches[branch] = {"last_checkpoint_epoch": now, "last_checkpoint_at": iso}
    save_state({"branches": branches})


def current_branch() -> str:
    return (_run(["git", "branch", "--show-current"]).stdout or "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Commit and push a green checkpoint on {PILOT_BRANCH_PREFIX}<name>."
    )
    parser.add_argument("--session-end", action="store_true", help="Allow a checkpoint before the minimum interval.")
    parser.add_argument("-m", "--message", default="", help="Commit message (accounting summary).")
    args = parser.parse_args(argv)

    branch = current_branch()
    if branch in {"main", "master"}:
        return _fail(f"refusing to publish from {branch}")
    if not is_accountant_pilot_branch(branch):
        return _fail(f"on '{branch}', expected '{PILOT_BRANCH_PREFIX}<name>'")
    if not (_run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False).stdout.strip()):
        # First publish may have no upstream yet; still only push the current pilot ref.
        pass
    else:
        upstream = _run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]).stdout.strip()
        if not upstream.endswith(branch):
            return _fail(f"upstream is {upstream}, not origin/{branch}")

    porcelain = _run(["git", "status", "--porcelain", "-u"]).stdout
    if not porcelain.strip():
        return _fail("nothing to checkpoint")
    for line in porcelain.splitlines():
        path = line[3:].strip()
        if is_forbidden_path(path):
            return _fail(f"forbidden path: {path}")

    last = branch_checkpoint_epoch(load_state(), branch)
    elapsed_min = (time.time() - last) / 60 if last else None
    if last and elapsed_min is not None and elapsed_min < CHECKPOINT_MIN_MINUTES and not args.session_end:
        return _fail(
            f"last checkpoint on {branch} was {elapsed_min:.0f} minutes ago "
            f"(minimum {CHECKPOINT_MIN_MINUTES}). Use --session-end if the day is over."
        )

    gate = subprocess.run([sys.executable, str(ROOT / "scripts" / "quality_gate.py")], cwd=ROOT)
    if gate.returncode != 0:
        return _fail("quality_gate failed")

    _run(["git", "add", "-A"])
    message = (args.message or "").strip() or (
        "Accountant-pilot checkpoint "
        + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )
    commit = _run(["git", "commit", "-m", message], check=False)
    if commit.returncode != 0:
        return _fail(commit.stderr.strip() or "git commit failed")

    push = _run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], check=False)
    if push.returncode != 0:
        return _fail(push.stderr.strip() or "git push failed")

    record_checkpoint(branch)
    print(f"checkpoint pushed to origin/{branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
