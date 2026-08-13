from __future__ import annotations

import argparse
import subprocess
import sys

from markus_mcp.credentials_store import (
    is_configured,
    parse,
    parse_assignments,
    read_values,
    update_values,
    write_values,
)
from markus_mcp.cursor_skills import install_cursor_skills
from markus_mcp.paths import credentials_file, ensure_markus_dirs, markus_home


def ensure_credentials_template() -> dict[str, object]:
    path = credentials_file()
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    values = parse(raw)
    created = not path.exists()
    # Files written in the old positional layout have no assignments; rewrite them once so
    # every install converges on `key = value`.
    legacy = bool(raw) and "=" not in raw

    if created or legacy:
        write_values(
            path,
            {
                "saga_username": values.get("saga_username", ""),
                "saga_password": values.get("saga_password", ""),
                "smartbill_username": values.get("smartbill_username", ""),
                "smartbill_password": values.get("smartbill_password", ""),
                "smartbill_token": values.get("smartbill_token", ""),
                "smartbill_cif": values.get("smartbill_cif", ""),
            },
        )

    readme = markus_home() / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Markus data directory.\n\n"
            "1. private.data holds credentials as `key = value`, for example:\n"
            "     saga_username = 'you@example.com'\n"
            "     saga_password = 'your-password'\n"
            "     smartbill_token = 'your-api-token'\n"
            "     smartbill_username = 'you@example.com'  # optional; defaults to saga_username\n"
            "     smartbill_cif = 'RO12345678'            # optional until a live API call needs it\n"
            "2. In Cursor, reload MCP servers, then ask for health_check.\n"
            "3. Pair WhatsApp with whatsapp_web_pair and scan the QR screenshot.\n",
            encoding="utf-8",
        )

    return {
        "path": str(path),
        "created": created,
        "migrated": legacy,
        "configured": is_configured(read_values(path), "saga_username", "saga_password"),
    }


def _chromium_install_command() -> tuple[list[str], dict[str, str] | None]:
    """A frozen binary has no importable ``-m playwright``, so drive the bundled CLI directly."""
    if getattr(sys, "frozen", False):
        from playwright._impl._driver import compute_driver_executable, get_driver_env

        node, cli = compute_driver_executable()
        return [node, cli, "install", "chromium"], get_driver_env()
    return [sys.executable, "-m", "playwright", "install", "chromium"], None


def install_chromium() -> dict[str, object]:
    try:
        cmd, env = _chromium_install_command()
    except Exception as exc:  # noqa: BLE001 - report instead of crashing setup
        return {"ok": False, "error": str(exc), "command": None}
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    except OSError as exc:
        return {"ok": False, "error": str(exc), "command": cmd}
    return {
        "ok": completed.returncode == 0,
        "command": cmd,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-2000:],
        "stderr": (completed.stderr or "")[-2000:],
    }


def set_credentials(values: dict[str, str]) -> dict[str, object]:
    path = credentials_file()
    stored = update_values(path, {k: v for k, v in values.items() if v})
    return {
        "ok": True,
        "path": str(path),
        "keys_written": sorted(k for k, v in values.items() if v),
        "configured": is_configured(stored, "saga_username", "saga_password"),
    }


def prompt_credentials() -> dict[str, str]:
    import getpass

    username = input("SAGA email / username: ").strip()
    password = getpass.getpass("SAGA password: ")
    token = getpass.getpass("SmartBill API token (optional, Enter to skip): ")
    return {
        "saga_username": username,
        "saga_password": password,
        "smartbill_token": token.strip(),
    }


def set_credentials_cli() -> int:
    """Back ``--set-credentials``: read assignments from stdin, or prompt on a terminal.

    Credentials arrive on stdin rather than argv so they never show up in the process list.
    """
    ensure_markus_dirs()
    if sys.stdin is not None and not sys.stdin.isatty():
        values = parse_assignments(sys.stdin.read())
    else:
        values = prompt_credentials()

    payload = {k: v for k, v in values.items() if v}
    if not payload:
        print("No credentials provided; private.data was left unchanged.")
        return 1

    result = set_credentials(payload)
    print(f"Saved {', '.join(result['keys_written'])} to {result['path']}")
    return 0


def bootstrap(*, install_browser: bool = True) -> dict[str, object]:
    dirs = ensure_markus_dirs()
    creds = ensure_credentials_template()
    skills = install_cursor_skills()
    browser: dict[str, object] = {"skipped": True}
    if install_browser:
        browser = install_chromium()
    return {
        "ok": True,
        "dirs": dirs,
        "credentials": creds,
        "skills": skills,
        "chromium": browser,
        "next_steps": [
            f"Edit SAGA credentials: {creds['path']}",
            "Reload Cursor MCP servers",
            "Ask the agent to call health_check",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize Markus home directory and Chromium.")
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Only create directories and private.data template.",
    )
    parser.add_argument(
        "--set-credentials",
        action="store_true",
        help="Store credentials read from stdin (key=value lines) or prompt for them.",
    )
    args = parser.parse_args(argv)
    if args.set_credentials:
        return set_credentials_cli()

    result = bootstrap(install_browser=not args.skip_browser)
    print(f"Markus home: {result['dirs']['markus_home']}")
    print(f"Data dir:    {result['dirs']['data_dir']}")
    creds = result["credentials"]
    state = "configured" if creds["configured"] else "needs saga_username / saga_password"
    print(f"Credentials: {creds['path']} ({state})")
    skills = result.get("skills") or {}
    if skills.get("ok"):
        print(f"Skills:      {skills.get('skills_dir')} ({len(skills.get('installed') or [])} installed)")
    elif skills:
        print(f"Skills:      FAILED missing {skills.get('missing')}")
    chromium = result.get("chromium") or {}
    if chromium.get("skipped"):
        print("Chromium:    skipped")
    elif chromium.get("ok"):
        print("Chromium:    installed")
    else:
        print("Chromium:    FAILED")
        if chromium.get("stderr"):
            print(chromium["stderr"])
        return 1
    for step in result["next_steps"]:
        print(f"- {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
