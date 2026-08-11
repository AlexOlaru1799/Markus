#!/usr/bin/env python3
"""One-off discovery helper for SAGA WEB partners endpoints."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("MARKUS_DATA_DIR", "/data")
os.environ.setdefault("MARKUS_HOST_DATA_DIR", "/Users/cristianolaru/Desktop/Markus/data")
os.environ.setdefault("SAGA_CREDENTIALS_FILE", "/app/private.data")
os.environ.setdefault("SAGA_HEADLESS", "false")
os.environ.setdefault("DISPLAY", os.environ.get("DISPLAY", ":99"))

from markus_mcp.tools.saga import session as saga_session  # noqa: E402


def main() -> None:
    print("login...", flush=True)
    login_result = saga_session.login()
    print(json.dumps({k: v for k, v in login_result.items() if k != "error"}, ensure_ascii=False, indent=2))
    if login_result.get("error"):
        print("ERROR", login_result["error"])
        return

    def explore(page):
        saga_session.clear_capture()
        # Try common menu texts for partners.
        for label in ("Parteneri", "Nomenclatoare", "Clienti", "Clienți", "Terti", "Terți"):
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    print("clicked", label)
                except Exception as exc:
                    print("click failed", label, exc)

        # Search page for partner-like routes via links.
        hrefs = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.getAttribute('href')).filter(Boolean).slice(0, 200)",
        )
        interesting = [h for h in hrefs if any(t in (h or "").casefold() for t in ("partener", "client", "tert", "nomencl"))]
        print("interesting_hrefs", interesting[:50])

        page.wait_for_timeout(3000)
        shot = saga_session._save_screenshot(page, "saga-partners-explore.png")
        capture = saga_session._dump_capture("network-partners-explore.json")
        return {"shot": shot, "capture": capture, "url": page.url}

    result = saga_session.run_in_session(explore)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # Print API-ish requests from capture files.
    capture_path = Path(os.environ["MARKUS_DATA_DIR"]) / "saga" / "network-partners-explore.json"
    if capture_path.exists():
        data = json.loads(capture_path.read_text())
        apiish = [
            item
            for item in data
            if item.get("resource_type") in {"xhr", "fetch"}
            or "/api" in (item.get("url") or "").casefold()
            or "partener" in (item.get("url") or "").casefold()
        ]
        print("apiish_count", len(apiish))
        for item in apiish[:80]:
            print(item.get("method"), item.get("status"), item.get("url"))


if __name__ == "__main__":
    main()
