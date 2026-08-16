"""Lock / unlock a journal document via ExecutaValidare / Devalidare. Not implied by create."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import session as saga_session


def _paths(spec, *, devalidate: bool) -> tuple[str, ...]:
    route = spec.route
    if devalidate:
        return (f"{route}/Devalidare", f"{route}/ExecutaDevalidare")
    return (f"{route}/ExecutaValidare", f"{route}/Validare")


def validate_document(
    screen: str,
    pk: str,
    *,
    devalidate: bool = False,
    confirm_write: bool = False,
) -> dict[str, Any]:
    spec = saga_registry.get_screen(screen)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown screen '{screen}'.",
            "screens": saga_registry.list_operation_ids(),
        }
    key = (pk or "").strip()
    if not key:
        return {"ok": False, "error": "pk is required (document id / NrDoc)."}
    action = "devalidate_document" if devalidate else "validate_document"
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": action,
            "screen": spec.operation,
            "pk": key,
            "preview": {"screen": spec.operation, "pk": key, "devalidate": devalidate},
            "details": (
                "Preview only — creating a row does not lock it. This calls "
                f"{'Devalidare' if devalidate else 'ExecutaValidare'} on {spec.title}. "
                "Confirm then call with confirm_write=true."
            ),
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        from markus_mcp.tools.saga import context as saga_context

        blocked = saga_context.assert_writable(page, screen=spec.operation)
        if blocked:
            return blocked
        opened = saga_grid.open_screen(page, spec.route)
        if not opened.get("ok"):
            return {"ok": False, **opened}
        last: dict[str, Any] = {}
        form = {"Id": key, "id": key, spec.pk: key, "NrDoc": key}
        for path in _paths(spec, devalidate=devalidate):
            last = saga_protocol.ajax(page, "POST", path, form=form)
            if last.get("ok_http"):
                return {
                    "ok": True,
                    "action": action,
                    "screen": spec.operation,
                    "pk": key,
                    "endpoint": last.get("endpoint"),
                    "response": last.get("response"),
                    "url": page.url,
                    "screenshot_path": saga_session._save_screenshot(page, f"saga-{action}.png"),
                }
        return {
            "ok": False,
            "error": f"{action} endpoint did not succeed on this WEB build.",
            "last_status": last.get("status"),
            "last_endpoint": last.get("endpoint"),
            "url": page.url,
        }

    return saga_session.run_in_session(_run)
