"""Delete SAGA documents and partners on the connected firm.

Scope is the operational grids the user asked for: Intrări / Ieșiri with and
without valută, then Furnizori and Clienți. Chart of accounts, salaries,
month-close, and company config are not touched.

Documents are removed first (FK), after devalidating locked rows. Mutations
use the same confirm_write preview gate as the other SAGA write tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin

from markus_mcp.tools.saga import partners as saga_partners
from markus_mcp.tools.saga import session as saga_session


SAMPLE_LIMIT = 10
BATCH_SIZE = 200
VALIDATED_VALUES = {"v", "1", "true", "da", "yes"}

# jQuery $.ajax default is GET. Ex-style CRUD uses POST. Try both.
_DELETE_METHODS = ("POST", "GET")


@dataclass(frozen=True)
class WipeTarget:
    key: str
    title: str
    kind: str  # "document" | "partner"
    route: str
    table: str
    get_data: str
    delete: str
    devalidate: str | None
    pk_fields: tuple[str, ...]
    label_fields: tuple[str, ...]
    ins_mod_table: str


# Documents first so partners are not blocked by remaining invoices.
WIPE_TARGETS: tuple[WipeTarget, ...] = (
    WipeTarget(
        key="intrari_valuta",
        title="Intrări valută",
        kind="document",
        route="IntrariValuta",
        table="IntrariValuta",
        get_data="IntrariValuta/GetData_IntrariValuta",
        delete="IntrariValuta/Delete_IntrariValuta",
        devalidate="IntrariValuta/ExecutaDevalidare",
        pk_fields=("ID_Intrare", "Id", "ID"),
        label_fields=("NrDoc", "Furnizor", "Client", "Data", "Moneda", "Total", "Validat"),
        ins_mod_table="INTRD",
    ),
    WipeTarget(
        key="intrari",
        title="Intrări",
        kind="document",
        route="Intrari",
        table="Intrari",
        get_data="Intrari/GetData_Intrari",
        delete="Intrari/Delete_Intrari",
        devalidate="Intrari/ExecutaDevalidare",
        pk_fields=("ID_Intrare", "Id", "ID"),
        label_fields=("NrDoc", "Furnizor", "Client", "Data", "Total", "Validat"),
        ins_mod_table="FACTURI",
    ),
    WipeTarget(
        key="iesiri_valuta",
        title="Ieșiri valută",
        kind="document",
        route="IesiriValuta",
        table="IesiriValuta",
        get_data="IesiriValuta/GetData_IesiriValuta",
        delete="IesiriValuta/Delete_IesiriValuta",
        devalidate="IesiriValuta/ExecutaDevalidare",
        pk_fields=("ID_Iesire", "Id", "ID"),
        label_fields=("NrDoc", "Client", "Data", "Valuta", "Total", "Validat"),
        ins_mod_table="EXPORT",
    ),
    WipeTarget(
        key="iesiri",
        title="Ieșiri",
        kind="document",
        route="Iesiri",
        table="Iesiri",
        get_data="Iesiri/GetData_Iesiri",
        delete="Iesiri/Delete_Iesiri",
        devalidate="Iesiri/ExecutaDevalidare",
        pk_fields=("ID_Iesire", "Id", "ID"),
        label_fields=("NrDoc", "Client", "Data", "Total", "Validat"),
        ins_mod_table="IESIRI",
    ),
    WipeTarget(
        key="furnizori",
        title="Furnizori",
        kind="partner",
        route="Furnizori",
        table="Furnizori",
        get_data="Furnizori/GetData_Furnizori",
        delete="Furnizori/Delete_Furnizori",
        devalidate=None,
        pk_fields=("Cod", "Id", "ID"),
        label_fields=("Cod", "Denumire", "CodFiscal", "CUI"),
        ins_mod_table="FURNIZOR",
    ),
    WipeTarget(
        key="clienti",
        title="Clienți",
        kind="partner",
        route="Clienti",
        table="Clienti",
        get_data="Clienti/GetData_Clienti",
        delete="Clienti/Delete_Clienti",
        devalidate=None,
        pk_fields=("Cod", "Id", "ID"),
        label_fields=("Cod", "Denumire", "CodFiscal", "CUI"),
        ins_mod_table="CLIENTI",
    ),
)

TARGETS_BY_KEY = {item.key: item for item in WIPE_TARGETS}
DEFAULT_TARGET_KEYS = tuple(item.key for item in WIPE_TARGETS)


def allowed_targets() -> list[dict[str, str]]:
    return [{"key": item.key, "title": item.title, "kind": item.kind} for item in WIPE_TARGETS]


def wipe_data(*, confirm_write: bool = False, targets: str = "") -> dict[str, Any]:
    selected, error = _parse_targets(targets)
    if error:
        return error

    def _preview(browser_page):
        page = saga_partners._ready(browser_page)
        return _build_preview(page, selected)

    preview = saga_session.run_in_session(_preview)
    if not preview.get("ok"):
        return preview
    if not confirm_write:
        return {
            "ok": False,
            "requires_confirmation": True,
            "action": "wipe_data",
            "preview": preview,
            "details": (
                "Preview only — this permanently deletes the listed rows on the "
                f"connected firm ({preview.get('firm_name') or 'unknown'}, "
                f"CodFirma {preview.get('firm_code') or '?'}). "
                "Does not wipe plan de conturi, salarii, închidere lună, or config. "
                "Ask the user to confirm the firm and counts, then call again with "
                "confirm_write=true."
            ),
        }

    def _run(browser_page):
        page = saga_partners._ready(browser_page)
        return _wipe_confirmed(page, selected, preview)

    return saga_session.run_in_session(_run)


def _parse_targets(raw: str | list[str] | None) -> tuple[list[WipeTarget], dict[str, Any] | None]:
    if raw is None or raw == "" or raw == []:
        keys = list(DEFAULT_TARGET_KEYS)
    elif isinstance(raw, list):
        keys = [str(item).strip() for item in raw if str(item).strip()]
    else:
        keys = [part.strip() for part in str(raw).replace(";", ",").split(",") if part.strip()]

    if not keys or any(key.casefold() in {"all", "*", "everything"} for key in keys):
        return list(WIPE_TARGETS), None

    unknown = [key for key in keys if key not in TARGETS_BY_KEY]
    if unknown:
        return [], {
            "ok": False,
            "error": f"Unknown wipe target(s): {', '.join(unknown)}",
            "allowed_targets": allowed_targets(),
        }

    seen: set[str] = set()
    ordered: list[WipeTarget] = []
    for item in WIPE_TARGETS:
        if item.key in keys and item.key not in seen:
            ordered.append(item)
            seen.add(item.key)
    return ordered, None


def _build_preview(page, selected: list[WipeTarget]) -> dict[str, Any]:
    firm = _firm_context(page)
    grids: list[dict[str, Any]] = []
    total = 0
    for target in selected:
        listed = _list_rows(page, target)
        count = int(listed.get("count") or 0)
        total += count
        grids.append(
            {
                "target": target.key,
                "title": target.title,
                "count": count,
                "validated_count": listed.get("validated_count", 0),
                "sample": listed.get("sample") or [],
                "error": listed.get("error"),
            }
        )
    return {
        "ok": True,
        "firm_name": firm.get("firm_name"),
        "firm_code": firm.get("firm_code"),
        "interval_start": firm.get("interval_start"),
        "interval_end": firm.get("interval_end"),
        "user": firm.get("user"),
        "total_rows": total,
        "targets": [item.key for item in selected],
        "grids": grids,
        "not_wiped": [
            "plan de conturi",
            "articole / gestiuni",
            "salarii",
            "închidere lună",
            "configurare societate",
        ],
        "note": (
            "Wipe lists rows visible in the current SAGA toolbar interval "
            f"({firm.get('interval_start') or '?'} – {firm.get('interval_end') or '?'}). "
            "Documents outside that interval are not deleted."
        ),
        "url": page.url,
        "screenshot_path": saga_session._save_screenshot(page, "saga-wipe-preview.png"),
    }


def _wipe_confirmed(page, selected: list[WipeTarget], preview: dict[str, Any]) -> dict[str, Any]:
    saga_session.clear_capture()
    results: list[dict[str, Any]] = []
    deleted_total = 0
    failed_total = 0
    remaining_total = 0

    for target in selected:
        opened = _open_screen(page, target)
        listed = _list_rows(page, target)
        rows = listed.get("rows") or []
        deleted = 0
        failed: list[dict[str, Any]] = []
        for row in rows:
            outcome = _wipe_row(page, target, row)
            if outcome.get("ok"):
                deleted += 1
            else:
                failed.append(outcome)
        remaining_listed = _list_rows(page, target)
        remaining = int(remaining_listed.get("count") or 0)
        deleted_total += deleted
        failed_total += len(failed)
        remaining_total += remaining
        results.append(
            {
                "target": target.key,
                "title": target.title,
                "opened": opened.get("ok"),
                "attempted": len(rows),
                "deleted": deleted,
                "failed": failed[:20],
                "failed_count": len(failed),
                "remaining": remaining,
                "remaining_sample": remaining_listed.get("sample") or [],
                "list_error": listed.get("error"),
            }
        )

    ok = failed_total == 0 and remaining_total == 0
    return {
        "ok": ok,
        "action": "wipe_data",
        "firm_name": preview.get("firm_name"),
        "firm_code": preview.get("firm_code"),
        "interval_start": preview.get("interval_start"),
        "interval_end": preview.get("interval_end"),
        "deleted_total": deleted_total,
        "failed_total": failed_total,
        "remaining_total": remaining_total,
        "results": results,
        "url": page.url,
        "screenshot_path": saga_session._save_screenshot(page, "saga-wipe-done.png"),
        "capture_path": saga_session._dump_capture("network-saga-wipe.json"),
        "error": None
        if ok
        else (
            f"Wipe finished with {failed_total} failed delete(s) and "
            f"{remaining_total} row(s) still listed. See results."
        ),
    }


def _firm_context(page) -> dict[str, Any]:
    probed = _ajax(page, "GET", "Home/LoadOperationalData")
    body = probed.get("response") if isinstance(probed.get("response"), dict) else {}
    toolbar = body.get("Toolbar") if isinstance(body.get("Toolbar"), dict) else {}
    user = body.get("Utilizator") if isinstance(body.get("Utilizator"), dict) else {}
    return {
        "firm_name": toolbar.get("DenumireFirma"),
        "firm_code": toolbar.get("CodFirma"),
        "interval_start": toolbar.get("IntervalStart"),
        "interval_end": toolbar.get("IntervalEnd"),
        "user": user.get("COD") or toolbar.get("DenumireUtilizator"),
        "raw_ok": probed.get("ok_http"),
    }


def _open_screen(page, target: WipeTarget) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", target.route)
    current = (page.url or "").casefold()
    if f"/sagac/{target.route.casefold()}" in current:
        return {"ok": True, "url": page.url, "via": "current"}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        try:
            page.goto(url, wait_until="commit", timeout=60_000)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "url": page.url}
    page.wait_for_timeout(1_200)
    return {"ok": True, "url": page.url, "via": "route"}


def _list_rows(page, target: WipeTarget) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    skip = 0
    reported_count: int | None = None
    last_error = None
    while True:
        params = {"RequestSetup": _request_setup(skip=skip, batch_size=BATCH_SIZE)}
        probed = _ajax(page, "GET", target.get_data, params=params)
        if not probed.get("ok_http"):
            last_error = (
                f"GetData failed HTTP {probed.get('status')} on {target.get_data}"
            )
            break
        body = probed.get("response")
        batch = _rows_from_payload(body)
        if isinstance(body, dict) and body.get("rowsCount") is not None:
            try:
                reported_count = int(body.get("rowsCount"))
            except (TypeError, ValueError):
                reported_count = reported_count
        rows.extend(batch)
        if not batch or len(batch) < BATCH_SIZE:
            break
        skip += len(batch)
        if reported_count is not None and skip >= reported_count:
            break
        if skip > 20_000:
            last_error = "Stopped listing after 20000 rows."
            break
    count = reported_count if reported_count is not None else len(rows)
    validated = sum(1 for row in rows if _is_validated(row))
    return {
        "ok": last_error is None,
        "error": last_error,
        "count": count,
        "validated_count": validated,
        "rows": rows,
        "sample": [_row_sample(target, row) for row in rows[:SAMPLE_LIMIT]],
    }


def _wipe_row(page, target: WipeTarget, row: dict[str, Any]) -> dict[str, Any]:
    pk = _row_pk(target, row)
    sample = _row_sample(target, row)
    if not pk:
        return {"ok": False, "error": "Missing primary key.", "row": sample}
    devalidated = None
    if target.devalidate and _is_validated(row):
        devalidated = _devalidate(page, target, row, pk)
        if not devalidated.get("ok"):
            # Still try delete — some rows delete without a prior devalidate.
            pass
    deleted = _delete_row(page, target, pk)
    if deleted.get("ok"):
        _executa_ins_mod(page, target, pk)
        return {
            "ok": True,
            "pk": pk,
            "row": sample,
            "devalidated": devalidated,
            "via": deleted.get("via"),
        }
    if target.devalidate and not (devalidated or {}).get("ok"):
        devalidated = _devalidate(page, target, row, pk)
        deleted = _delete_row(page, target, pk)
        if deleted.get("ok"):
            _executa_ins_mod(page, target, pk)
            return {
                "ok": True,
                "pk": pk,
                "row": sample,
                "devalidated": devalidated,
                "via": deleted.get("via"),
                "retried_after_devalidate": True,
            }
    return {
        "ok": False,
        "pk": pk,
        "row": sample,
        "error": deleted.get("error") or "Delete failed.",
        "devalidated": devalidated,
        "response": deleted.get("response"),
    }


def _devalidate(page, target: WipeTarget, row: dict[str, Any], pk: str) -> dict[str, Any]:
    if not target.devalidate:
        return {"ok": True, "skipped": True}
    data = {
        "IdFactura": pk,
        "Data": str(row.get("Data") or "").strip(),
        "Tip": str(row.get("Tip") or "").strip(),
        "SenderID": _sender_id(page),
    }
    result = _ajax(page, "GET", target.devalidate, params=data)
    parsed = result.get("response")
    if _is_soft_success(parsed, result.get("ok_http")):
        return {"ok": True, "via": "devalidate", "response": parsed}
    if isinstance(parsed, dict) and parsed.get("type") == "Choice":
        flag = str(parsed.get("flagId") or "").strip()
        if flag:
            _ajax(page, "GET", "Home/CheckFlag", params={"Id": flag, "Status": "true", "Aux": ""})
        result = _ajax(page, "GET", target.devalidate, params=data)
        parsed = result.get("response")
        if _is_soft_success(parsed, result.get("ok_http")):
            return {"ok": True, "via": "devalidate_choice", "response": parsed}
    # POST fallback — some screens reject GET.
    result = _ajax(page, "POST", target.devalidate, form=data)
    parsed = result.get("response")
    if _is_soft_success(parsed, result.get("ok_http")):
        return {"ok": True, "via": "devalidate_post", "response": parsed}
    return {
        "ok": False,
        "error": _status_text(parsed) or "ExecutaDevalidare failed.",
        "response": parsed,
    }


def _delete_row(page, target: WipeTarget, pk: str) -> dict[str, Any]:
    sender = _sender_id(page)
    # Ex-style (Clienti/Furnizori and newer grids).
    ex = _delete_ex(page, target, pk)
    if ex.get("ok"):
        return ex
    # Classic AdvancedControls: Id + _CHECKED handshake (often GET).
    classic = _delete_classic(page, target, pk, sender)
    if classic.get("ok"):
        return classic
    return {
        "ok": False,
        "error": classic.get("error") or ex.get("error") or "Delete failed.",
        "response": classic.get("response") or ex.get("response"),
        "via": "api",
    }


def _delete_ex(page, target: WipeTarget, pk: str) -> dict[str, Any]:
    form: dict[str, str] = {"ID": pk, "UserValidationFlags": "[]"}
    result = _ajax(page, "POST", target.delete, form=form)
    parsed = result.get("response")
    if isinstance(parsed, dict) and parsed.get("success") is True:
        return {"ok": True, "via": "api_ex", "response": parsed}
    if isinstance(parsed, dict) and parsed.get("errorCode") == "ValidateData":
        flags = []
        for flag in parsed.get("validationFlags") or []:
            if not isinstance(flag, dict):
                continue
            flag_id = flag.get("id") or flag.get("ID")
            if flag_id:
                flags.append({"ID": flag_id, "UserChoice": "Yes"})
        if flags:
            form = {
                "ID": pk,
                "UserValidationFlags": json.dumps(flags, ensure_ascii=False),
            }
            result = _ajax(page, "POST", target.delete, form=form)
            parsed = result.get("response")
            if isinstance(parsed, dict) and parsed.get("success") is True:
                return {"ok": True, "via": "api_ex", "response": parsed}
    return {
        "ok": False,
        "error": _status_text(parsed) or "Ex delete failed.",
        "response": parsed,
    }


def _delete_classic(page, target: WipeTarget, pk: str, sender: str) -> dict[str, Any]:
    last_error = "Classic delete failed."
    last_response: Any = None
    for method in _DELETE_METHODS:
        first = _ajax(
            page,
            method,
            target.delete,
            params={"Id": pk, "_CHECKED": "false", "SenderID": sender}
            if method == "GET"
            else None,
            form={"Id": pk, "_CHECKED": "false", "SenderID": sender}
            if method == "POST"
            else None,
        )
        parsed = first.get("response")
        last_response = parsed
        if isinstance(parsed, dict) and parsed.get("type") == "Choice":
            flag = str(parsed.get("flagId") or "").strip()
            if flag:
                _ajax(
                    page,
                    "GET",
                    "Home/CheckFlag",
                    params={"Id": flag, "Status": "true", "Aux": ""},
                )
            checked_form = {
                "Id": pk,
                "_CHECKED": "true",
                "SenderID": sender,
            }
            if flag:
                checked_form["Type"] = flag
            second = _ajax(
                page,
                method,
                target.delete,
                params=checked_form if method == "GET" else None,
                form=checked_form if method == "POST" else None,
            )
            parsed = second.get("response")
            last_response = parsed
            if _is_delete_done(parsed, second.get("ok_http")):
                return {"ok": True, "via": f"api_classic_{method.lower()}", "response": parsed}
            last_error = _status_text(parsed) or last_error
            continue
        if isinstance(parsed, dict) and parsed.get("type") == "Warning":
            last_error = _status_text(parsed) or last_error
            continue
        if isinstance(parsed, dict) and parsed.get("type") == "Validation":
            second = _ajax(
                page,
                method,
                target.delete,
                params={"Id": pk, "_CHECKED": "true", "SenderID": sender}
                if method == "GET"
                else None,
                form={"Id": pk, "_CHECKED": "true", "SenderID": sender}
                if method == "POST"
                else None,
            )
            parsed = second.get("response")
            last_response = parsed
            if _is_delete_done(parsed, second.get("ok_http")):
                return {"ok": True, "via": f"api_classic_{method.lower()}", "response": parsed}
            last_error = _status_text(parsed) or last_error
            continue
        if _is_delete_done(parsed, first.get("ok_http")):
            return {"ok": True, "via": f"api_classic_{method.lower()}", "response": parsed}
        last_error = _status_text(parsed) or last_error
    return {"ok": False, "error": last_error, "response": last_response}


def _executa_ins_mod(page, target: WipeTarget, pk: str) -> None:
    try:
        _ajax(
            page,
            "GET",
            "Home/ExecutaInsMMod",
            params={"Id": pk, "Tabela": target.ins_mod_table, "Tip": "S"},
        )
    except Exception:
        return


def _ajax(
    page,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", path.lstrip("/"))
    headers = saga_session._auth_headers(page)
    try:
        if method.upper() == "GET":
            url = f"{absolute}?{urlencode(params or {})}" if params else absolute
            response = page.request.get(url, headers=headers, timeout=45_000)
        else:
            response = page.request.post(
                absolute,
                form=form or params or {},
                headers=headers,
                timeout=45_000,
            )
    except Exception as exc:
        return {
            "ok_http": False,
            "status": 0,
            "endpoint": absolute,
            "error": str(exc),
            "response": None,
        }
    content_type = response.headers.get("content-type", "")
    try:
        parsed: Any = response.json() if "json" in content_type else response.text()
    except Exception:
        parsed = response.text()
    if isinstance(parsed, str) and parsed.strip()[:1] in "{[":
        try:
            parsed = json.loads(parsed)
        except Exception:
            pass
    return {
        "ok_http": bool(response.ok),
        "status": response.status,
        "endpoint": absolute,
        "response": parsed,
    }


def _request_setup(*, skip: int = 0, batch_size: int = BATCH_SIZE) -> str:
    return json.dumps(
        {
            "FilterSearchType": 1,
            "FilterCaseSensitive": False,
            "FilterCurrentTable": False,
            "Skip": max(skip, 0),
            "BatchSize": max(batch_size, 1),
            "GetRowsCount": True,
        },
        separators=(",", ":"),
    )


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "Data", "rows", "Rows", "items", "Items", "result", "Result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            if nested:
                return nested
    return []


def _row_pk(target: WipeTarget, row: dict[str, Any]) -> str:
    for key in target.pk_fields:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _row_sample(target: WipeTarget, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in target.label_fields + target.pk_fields:
        if key in row and key not in out:
            out[key] = row.get(key)
    return out


def _is_validated(row: dict[str, Any]) -> bool:
    value = row.get("Validat")
    if value is None:
        return False
    text = str(value).strip().casefold()
    return text in VALIDATED_VALUES


def _sender_id(page) -> str:
    try:
        value = page.evaluate(
            "() => (typeof tabID !== 'undefined' && tabID != null) ? String(tabID) : '0'"
        )
        if value:
            return str(value)
    except Exception:
        pass
    return "0"


def _status_text(parsed: Any) -> str:
    if isinstance(parsed, dict):
        for key in ("status", "message", "error", "Message"):
            value = parsed.get(key)
            if value:
                return str(value).strip()
    if isinstance(parsed, str) and parsed.strip():
        return parsed.strip()[:400]
    return ""


def _is_soft_success(parsed: Any, http_ok: bool | None) -> bool:
    if not http_ok:
        return False
    if parsed is None or parsed == "" or parsed == {}:
        return True
    if isinstance(parsed, dict):
        if parsed.get("success") is False:
            return False
        if parsed.get("type") in ("Warning", "Error"):
            return False
        if parsed.get("type") == "Choice":
            return False
        if parsed.get("success") is True:
            return True
        if parsed.get("type") == "Validation":
            return True
    return bool(http_ok)


def _is_delete_done(parsed: Any, http_ok: bool | None) -> bool:
    if not http_ok:
        return False
    if parsed is None or parsed == "" or parsed == {}:
        return True
    if isinstance(parsed, dict):
        if parsed.get("success") is False:
            return False
        if parsed.get("type") in ("Warning", "Choice", "Error"):
            return False
        if parsed.get("success") is True:
            return True
        # Second _CHECKED=true call often returns Validation + deleted id.
        if parsed.get("type") == "Validation":
            return True
    if isinstance(parsed, str) and "<html" in parsed[:200].casefold():
        return False
    return bool(http_ok)
