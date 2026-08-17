"""Firm / user / interval / rights context for the connected SAGA session."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import session as saga_session


def _get(page, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
    return saga_protocol.ajax(page, "GET", path, params=params, timeout=30_000)


def load_operational_data(page) -> dict[str, Any]:
    probed = _get(page, "Home/LoadOperationalData")
    body = probed.get("response") if isinstance(probed.get("response"), dict) else {}
    toolbar = body.get("Toolbar") if isinstance(body.get("Toolbar"), dict) else {}
    user = body.get("Utilizator") if isinstance(body.get("Utilizator"), dict) else {}
    societ = body.get("Societ") if isinstance(body.get("Societ"), dict) else {}
    config = body.get("Configurare") if isinstance(body.get("Configurare"), dict) else {}
    return {
        "ok": bool(probed.get("ok_http")),
        "endpoint": probed.get("endpoint"),
        "firm_name": toolbar.get("DenumireFirma") or societ.get("Denumire"),
        "firm_code": toolbar.get("CodFirma"),
        "interval_start": toolbar.get("IntervalStart"),
        "interval_end": toolbar.get("IntervalEnd"),
        "user": user.get("COD") or toolbar.get("DenumireUtilizator"),
        "tip_contabilitate": body.get("TipContabilitate") or toolbar.get("TipContabilitate"),
        "fara_stocuri": body.get("FaraStocuri"),
        "toolbar": toolbar,
        "societ": societ,
        "configurare": config,
        "raw": body if probed.get("ok_http") else None,
        "error": None if probed.get("ok_http") else saga_protocol.status_text(probed.get("response")),
    }


def load_rights(page) -> dict[str, Any]:
    probed = _get(page, "Home/LoadDrepturiEcrane")
    body = probed.get("response")
    return {
        "ok": bool(probed.get("ok_http")),
        "endpoint": probed.get("endpoint"),
        "rights": body if probed.get("ok_http") else None,
        "error": None if probed.get("ok_http") else saga_protocol.status_text(body),
    }


def load_closed_period(page) -> dict[str, Any]:
    probed = _get(page, "Home/GetInchidereCurenta")
    if not probed.get("ok_http"):
        return {
            "ok": False,
            "unknown": True,
            "endpoint": probed.get("endpoint"),
            "closed": None,
            "raw": probed.get("response"),
        }
    return {
        "ok": True,
        "unknown": False,
        "endpoint": probed.get("endpoint"),
        "closed": probed.get("response"),
        "raw": probed.get("response"),
    }


def is_still_connected(page) -> dict[str, Any]:
    probed = _get(page, "Home/IsStillConnected")
    return {
        "ok": bool(probed.get("ok_http")),
        "connected": probed.get("response") if probed.get("ok_http") else False,
        "endpoint": probed.get("endpoint"),
    }


def closed_period_notice(closed: Any) -> str | None:
    """Human warning when GetInchidereCurenta says a month is closed."""
    if closed in (None, False, 0, "0", "", "null", "None"):
        return None
    if closed is True or (isinstance(closed, str) and closed.strip().casefold() in {"true", "da", "yes"}):
        return (
            "SAGA reports a closed period (Home/GetInchidereCurenta). "
            "Tell the user before posting. If they still want the write, continue after confirm_write. "
            "SAGA itself may refuse. Reports for that interval may still run."
        )
    if isinstance(closed, dict):
        useful = [
            value
            for value in closed.values()
            if value not in (None, False, 0, "0", "", [], {})
        ]
        if not useful:
            return None
    return (
        "SAGA reports a closed period (Home/GetInchidereCurenta). "
        "Tell the user before posting. If they still want the write, continue after confirm_write. "
        "SAGA itself may refuse. Reports for that interval may still run."
    )


def period_is_closed(closed: Any) -> bool:
    return closed_period_notice(closed) is not None


def _compact_name(value: str) -> str:
    return "".join(ch for ch in (value or "").casefold() if ch.isalnum())


def _screen_aliases(screen: str) -> set[str]:
    """Match operation ids to SAGA Ecran/Controller names (Clienti, JurnalDeBanca)."""
    aliases: set[str] = set()

    def _add(value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        aliases.add(text.casefold())
        compact = _compact_name(text)
        if compact:
            aliases.add(compact)

    _add(screen)
    try:
        from markus_mcp.tools.saga import registry as saga_registry

        spec = saga_registry.get_screen(screen)
        if spec:
            _add(spec.operation)
            _add(spec.route)
            _add(spec.title)
    except Exception:
        pass
    return aliases


def _right_rows(body: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(body, list):
        for item in body:
            rows.extend(_right_rows(item))
        return rows
    if not isinstance(body, dict):
        return rows
    keys = ("Ecran", "Nume", "Screen", "Controller", "controller", "Name")
    if any(key in body for key in keys):
        rows.append(body)
    for nested in ("Drepturi", "Ecrane", "data", "Data", "rights", "Items", "items"):
        if nested in body:
            rows.extend(_right_rows(body.get(nested)))
    return rows


def screen_write_denied(rights_body: Any, screen: str) -> bool:
    """True only on an explicit deny.

    Live LoadDrepturiEcrane polarity (SKY DEVEL CONSULT, 2026-08): Access=0 is
    allowed on Iesiri/Clienti/Furnizori; Access=1 is restricted (Salariati,
    State salarii). Adaugare/Stergere=0 remains an explicit operation deny.
    """
    needles = _screen_aliases(screen)
    if not needles or rights_body in (None, "", False):
        return False
    deny_values = {0, "0", False, "false", "False", "nu", "NU", "n", "N"}
    access_denied = {1, "1", True, "true", "True", "da", "DA"}
    for row in _right_rows(rights_body):
        names = [
            str(row.get(key) or "").strip().casefold()
            for key in ("Ecran", "Nume", "Screen", "Controller", "controller", "Name", "Cod")
        ]
        compact_names = {_compact_name(name) for name in names if name}
        if not (needles & set(names)) and not (needles & compact_names):
            continue
        for key in (
            "Adaugare",
            "Modificare",
            "Salvare",
            "Stergere",
            "Write",
            "DreptAdaugare",
            "DreptModificare",
            "CanAdd",
            "CanEdit",
            "CanDelete",
        ):
            if key in row and row.get(key) in deny_values:
                return True
        if "Access" in row and row.get("Access") in access_denied:
            return True
    return False


def assert_writable(page, *, screen: str = "", allow_closed: bool = False) -> dict[str, Any] | None:
    """Pre-flight LoadDrepturiEcrane. None = proceed.

    Closed month is not a Markus veto. Warn via saga_context; after the user
    confirms the write, continue. SAGA may still refuse. allow_closed is kept
    so existing callers do not break.
    """
    _ = allow_closed
    rights = load_rights(page)
    if rights.get("ok") and screen and screen_write_denied(rights.get("rights"), screen):
        return {
            "ok": False,
            "error": (
                f"LoadDrepturiEcrane denies writes on '{screen}'. "
                "The logged-in user cannot mutate this screen."
            ),
            "blocked": "rights",
            "screen": screen,
        }
    return None


def snapshot(page) -> dict[str, Any]:
    """Read-only firm/interval/rights payload for saga_context."""
    state = saga_session._detect_state(page)
    operational = load_operational_data(page) if state.logged_in else {"ok": False, "error": "Not logged in."}
    rights = load_rights(page) if state.logged_in and state.firm_selected else {"ok": False, "skipped": True}
    closed = load_closed_period(page) if state.logged_in and state.firm_selected else {"ok": False, "skipped": True}
    connected = is_still_connected(page) if state.logged_in else {"ok": False, "skipped": True}
    return {
        "ok": bool(state.logged_in and state.firm_selected),
        "logged_in": bool(state.logged_in),
        "firm_selected": bool(state.firm_selected),
        "needs_otp": bool(state.needs_otp),
        "needs_browser_authorization": bool(state.needs_browser_authorization),
        "url": page.url,
        "firm_name": operational.get("firm_name"),
        "firm_code": operational.get("firm_code"),
        "interval_start": operational.get("interval_start"),
        "interval_end": operational.get("interval_end"),
        "user": operational.get("user"),
        "tip_contabilitate": operational.get("tip_contabilitate"),
        "fara_stocuri": operational.get("fara_stocuri"),
        "closed_period": closed.get("closed") if closed.get("ok") else None,
        "closed_period_unknown": bool(closed.get("unknown")),
        "closed_period_warning": closed_period_notice(closed.get("closed") if closed.get("ok") else None),
        "connected": connected.get("connected") if connected.get("ok") else None,
        "rights_ok": bool(rights.get("ok")),
        "operational_ok": bool(operational.get("ok")),
        "details": (
            "Working interval and firm come from Home/LoadOperationalData. "
            "Named writes call assert_writable (LoadDrepturiEcrane) before mutating. "
            "A closed month is a warning, not a Markus veto."
        ),
    }


def get_context() -> dict[str, Any]:
    def _run(browser_page):
        return snapshot(browser_page)

    return saga_session.run_in_session(_run)


def _saga_date(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text[:10].split("-")
        return f"{day}.{month}.{year}"
    return text


def about() -> dict[str, Any]:
    """Despre / version. Read-only."""

    def _run(browser_page):
        from markus_mcp.tools.saga import grid as saga_grid
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        operational = load_operational_data(page)
        config = operational.get("configurare") if isinstance(operational.get("configurare"), dict) else {}
        societ = operational.get("societ") if isinstance(operational.get("societ"), dict) else {}
        versions: dict[str, Any] = {}
        for path in ("Home/GetVersiune", "Home/GetVersion", "Despre/GetData"):
            probed = _get(page, path)
            if probed.get("ok_http"):
                versions[path] = probed.get("response")
        opened = saga_grid.open_screen(page, "Despre")
        return {
            "ok": True,
            "firm_name": operational.get("firm_name"),
            "firm_code": operational.get("firm_code"),
            "user": operational.get("user"),
            "configurare_keys": sorted(str(key) for key in config.keys()),
            "societ_keys": sorted(str(key) for key in societ.keys()),
            "version_probes": versions,
            "despre_url": opened.get("url") if opened.get("ok") else None,
            "details": "Version fields vary by WEB build. Firm/user come from LoadOperationalData.",
        }

    return saga_session.run_in_session(_run)


def set_interval(
    interval_start: str,
    interval_end: str,
    *,
    confirm_write: bool = False,
) -> dict[str, Any]:
    start = _saga_date(interval_start)
    end = _saga_date(interval_end)
    if not start or not end:
        return {"ok": False, "error": "interval_start and interval_end are required (dd.mm.yyyy or YYYY-MM-DD)."}
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "set_interval",
            "preview": {"interval_start": start, "interval_end": end},
            "details": (
                "Preview only — will change the SAGA toolbar working interval. "
                "Confirm then call with confirm_write=true."
            ),
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        blocked = assert_writable(page, screen="set_interval", allow_closed=True)
        if blocked:
            return blocked
        form = {"IntervalStart": start, "IntervalEnd": end, "DataStart": start, "DataStop": end}
        last: dict[str, Any] = {}
        for path in ("Home/SetInterval", "Home/SalvareInterval", "Home/SetDataInterval"):
            last = saga_protocol.ajax(page, "POST", path, form=form)
            if last.get("ok_http"):
                after = snapshot(page)
                return {
                    "ok": True,
                    "changed": True,
                    "endpoint": last.get("endpoint"),
                    "interval_start": after.get("interval_start"),
                    "interval_end": after.get("interval_end"),
                    "requested": {"interval_start": start, "interval_end": end},
                    "url": page.url,
                }
        return {
            "ok": False,
            "error": "SetInterval endpoint did not succeed on this WEB build.",
            "last_status": last.get("status"),
            "last_endpoint": last.get("endpoint"),
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-set-interval-failed.png"),
        }

    return saga_session.run_in_session(_run)


def close_month(*, confirm_write: bool = False, confirm_phrase: str = "") -> dict[str, Any]:
    """Hard-gated month close. Cannot run unattended."""
    expected = "INCHIDE LUNA"
    if not confirm_write:
        ctx = get_context()
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "close_month",
            "preview": {
                "firm_name": ctx.get("firm_name"),
                "interval_start": ctx.get("interval_start"),
                "interval_end": ctx.get("interval_end"),
                "closed_period": ctx.get("closed_period"),
            },
            "details": (
                "HUMAN-GATED. Closing a SAGA month cannot be undone from Markus. "
                f"Only after the user explicitly OK's this firm, call again with "
                f"confirm_write=true and confirm_phrase='{expected}'."
            ),
        }
    if (confirm_phrase or "").strip() != expected:
        return {
            "ok": False,
            "error": f"confirm_phrase must be exactly '{expected}'. Refusing unattended month close.",
        }

    def _run(browser_page):
        from markus_mcp.tools.saga import grid as saga_grid
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        blocked = assert_writable(page, screen="inchidere_luna", allow_closed=True)
        if blocked:
            return blocked
        saga_grid.open_screen(page, "InchidereLuna")
        last: dict[str, Any] = {}
        for path in (
            "InchidereLuna/ExecutaInchidere",
            "InchidereLuna/InchideLuna",
            "Home/ExecutaInchidere",
        ):
            last = saga_protocol.ajax(page, "POST", path, form={})
            if last.get("ok_http"):
                after = snapshot(page)
                return {
                    "ok": True,
                    "closed": True,
                    "endpoint": last.get("endpoint"),
                    "closed_period": after.get("closed_period"),
                    "url": page.url,
                    "screenshot_path": saga_session._save_screenshot(page, "saga-close-month.png"),
                }
        return {
            "ok": False,
            "error": "Inchidere lună execute endpoint did not succeed. Use the SAGA UI.",
            "last_status": last.get("status"),
            "last_endpoint": last.get("endpoint"),
            "url": page.url,
            "screenshot_path": saga_session._save_screenshot(page, "saga-close-month-failed.png"),
        }

    return saga_session.run_in_session(_run)
