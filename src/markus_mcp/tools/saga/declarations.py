"""Human-gated ANAF/SPV declarations. Generate may download a local PDF; submit never runs unattended."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import reports as saga_reports
from markus_mcp.tools.saga import session as saga_session


SUBMIT_PHRASE = "TRIMITE DECLARATIE"

DECLARATIONS: dict[str, dict[str, Any]] = {
    "406": {
        "title": "Declarația 406 (SAF-T)",
        "report": "declaratie_406",
        "route": "InchidereLuna",
        "submit": (
            "InchidereLuna/TransmiteDeclaratie406",
            "D406/Transmite",
            "SAFT/Transmite",
        ),
    },
    "205": {
        "title": "Declarația 205",
        "report": "declaratie_205",
        "route": "InchidereLuna",
        "submit": ("InchidereLuna/TransmiteDeclaratie205", "D205/Transmite"),
    },
    "intrastat": {
        "title": "Declarația Intrastat",
        "report": "declaratie_intrastat",
        "route": "InchidereLuna",
        "submit": ("InchidereLuna/TransmiteIntrastat", "Intrastat/Transmite"),
    },
    "e_transport": {
        "title": "e-Transport",
        "report": "",
        "route": "ETransport",
        "submit": ("ETransport/Transmite", "eTransport/Transmite"),
    },
    "revisal": {
        "title": "REVISAL",
        "report": "",
        "route": "Revisal",
        "submit": ("Revisal/Transmite", "REVISAL/Transmite"),
    },
}


def _normalize(name: str) -> str:
    return (name or "").strip().casefold().replace(" ", "_").replace("-", "_")


def resolve_declaration(name: str) -> tuple[str, dict[str, Any]] | None:
    wanted = _normalize(name)
    aliases = {
        "406": "406",
        "d406": "406",
        "saft": "406",
        "declaratie_406": "406",
        "205": "205",
        "d205": "205",
        "declaratie_205": "205",
        "intrastat": "intrastat",
        "declaratie_intrastat": "intrastat",
        "e_transport": "e_transport",
        "etransport": "e_transport",
        "revisal": "revisal",
    }
    key = aliases.get(wanted)
    if key and key in DECLARATIONS:
        return key, DECLARATIONS[key]
    return None


def list_declarations() -> dict[str, Any]:
    items = [
        {
            "name": key,
            "title": spec["title"],
            "generate": bool(spec.get("report")),
            "submit_phrase": SUBMIT_PHRASE,
        }
        for key, spec in DECLARATIONS.items()
    ]
    return {
        "ok": True,
        "count": len(items),
        "declarations": items,
        "details": (
            "saga_generate_declaration downloads a local PDF when a generator exists. "
            f"saga_submit_declaration is HUMAN-GATED: confirm_write + confirm_phrase='{SUBMIT_PHRASE}'."
        ),
    }


def generate_declaration(name: str, *, filters: dict[str, Any] | None = None, format: str = "pdf") -> dict[str, Any]:
    if not (name or "").strip():
        return list_declarations()
    resolved = resolve_declaration(name)
    if resolved is None:
        listed = list_declarations()
        listed["ok"] = False
        listed["error"] = f"Unknown declaration '{name}'."
        return listed
    key, spec = resolved
    report = str(spec.get("report") or "").strip()
    if not report:
        return {
            "ok": False,
            "error": f"{spec['title']} has no local generator on this WEB build. Use the SAGA UI.",
            "declaration": key,
        }
    result = saga_reports.run_report(report, filters=filters, format=format)
    result["declaration"] = key
    result["title"] = spec["title"]
    return result


def submit_declaration(
    name: str,
    *,
    confirm_write: bool = False,
    confirm_phrase: str = "",
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not (name or "").strip():
        return list_declarations()
    resolved = resolve_declaration(name)
    if resolved is None:
        listed = list_declarations()
        listed["ok"] = False
        listed["error"] = f"Unknown declaration '{name}'."
        return listed
    key, spec = resolved
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "submit_declaration",
            "declaration": key,
            "preview": {"name": key, "title": spec["title"], "filters": dict(filters or {})},
            "details": (
                f"HUMAN-GATED. Submitting {spec['title']} to ANAF/SPV cannot be undone from Markus. "
                f"Only after the user explicitly OK's this filing, call again with "
                f"confirm_write=true and confirm_phrase='{SUBMIT_PHRASE}'."
            ),
        }
    if (confirm_phrase or "").strip() != SUBMIT_PHRASE:
        return {
            "ok": False,
            "error": f"confirm_phrase must be exactly '{SUBMIT_PHRASE}'. Refusing unattended submit.",
            "declaration": key,
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        from markus_mcp.tools.saga import context as saga_context

        blocked = saga_context.assert_writable(page, screen="declarations", allow_closed=True)
        if blocked:
            return blocked
        saga_grid.open_screen(page, str(spec.get("route") or "InchidereLuna"))
        last: dict[str, Any] = {}
        form = {str(k): str(v) for k, v in (filters or {}).items() if v not in (None, "")}
        for path in spec.get("submit") or ():
            last = saga_protocol.ajax(page, "POST", path, form=form)
            if last.get("ok_http"):
                return {
                    "ok": True,
                    "submitted": True,
                    "declaration": key,
                    "title": spec["title"],
                    "endpoint": last.get("endpoint"),
                    "response": last.get("response"),
                    "url": page.url,
                    "screenshot_path": saga_session._save_screenshot(page, f"saga-submit-{key}.png"),
                }
        return {
            "ok": False,
            "error": f"{spec['title']} submit endpoint did not succeed on this WEB build. Use the SAGA UI.",
            "declaration": key,
            "last_status": last.get("status"),
            "last_endpoint": last.get("endpoint"),
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, f"saga-submit-{key}-failed.png"),
        }

    return saga_session.run_in_session(_run)
