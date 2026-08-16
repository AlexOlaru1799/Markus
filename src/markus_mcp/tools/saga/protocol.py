"""SAGA AdvancedControls HTTP protocol: RequestSetup, handshake, classify."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode, urljoin

from markus_mcp.tools.saga import session as saga_session


Outcome = Literal["success", "needs_check", "needs_choice", "warning", "error"]
WriteStyle = Literal["classic", "ex"]
WriteOp = Literal["create", "edit", "delete"]

INT_KEYS = {"TVAI", "Validat"}
NUMERIC_KEYS = {
    "Curs",
    "Cantitate",
    "PretUnitarValuta",
    "PretUnitar",
    "TVA_ART",
    "ValoareValuta",
    "Valoare",
    "TVAValuta",
    "TVA",
    "TotalValuta",
    "Total",
    "NeachitatValuta",
    "Neachitat",
    "Adaos",
    "Suma",
}


@dataclass
class SagaResponse:
    outcome: Outcome
    raw: Any = None
    message: str | None = None
    flag_id: str | None = None
    validation_flags: list[dict[str, Any]] = field(default_factory=list)
    new_id: str | None = None
    ok_http: bool = False
    status: int = 0
    endpoint: str = ""
    request: dict[str, Any] | None = None
    chain: list[dict[str, Any]] = field(default_factory=list)
    via: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == "success"

    def as_dict(self) -> dict[str, Any]:
        parsed = self.raw
        return {
            "ok": self.ok,
            "outcome": self.outcome,
            "endpoint": self.endpoint,
            "status": self.status,
            "ok_http": self.ok_http,
            "response": parsed,
            "request": self.request,
            "flag_id": self.flag_id,
            "new_id": self.new_id,
            "message": self.message,
            "validation_flags": self.validation_flags,
            "chain": self.chain,
            "attempts": self.chain,
            "via": self.via,
            "error": None if self.ok else (self.message or status_text(parsed) or self.outcome),
        }


def request_setup(
    *,
    skip: int = 0,
    batch_size: int = 50,
    keyword: str | None = None,
    master_id: str | None = None,
    get_rows_count: bool = True,
    **extra: Any,
) -> str:
    payload: dict[str, Any] = {
        "FilterSearchType": 1,
        "FilterCaseSensitive": False,
        "FilterCurrentTable": False,
        "Skip": max(skip, 0),
        "BatchSize": max(batch_size, 0),
        "GetRowsCount": bool(get_rows_count),
    }
    if keyword:
        payload["FilterKeyword"] = keyword
    if master_id:
        payload["Id"] = master_id
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return json.dumps(payload, separators=(",", ":"))


def sender_id(page) -> str:
    try:
        value = page.evaluate(
            "() => (typeof tabID !== 'undefined' && tabID != null) ? String(tabID) : '0'"
        )
        if value:
            return str(value)
    except Exception:
        pass
    return "0"


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "data",
        "Data",
        "rows",
        "Rows",
        "items",
        "Items",
        "result",
        "Result",
        "parteneri",
        "Parteneri",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = rows_from_payload(value)
            if nested:
                return nested
    return []


def rows_count_from_payload(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("rowsCount", "RowsCount", "total", "Total", "count", "Count"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    nested = payload.get("data") or payload.get("Data")
    if isinstance(nested, dict):
        return rows_count_from_payload(nested)
    return None


def row_get(row: dict[str, Any], *names: str) -> str:
    lower = {str(key).casefold(): key for key in row}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
        key = lower.get(name.casefold())
        if key is not None and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""


def status_text(parsed: Any) -> str:
    if isinstance(parsed, dict):
        for key in ("status", "message", "error", "Message"):
            value = parsed.get(key)
            if value:
                return str(value).strip()
    if isinstance(parsed, str) and parsed.strip():
        return parsed.strip()[:400]
    return ""


def status_is_success(status: str) -> bool:
    """Numeric new-id, Succes, or SAGA's 'Deleted succesfully.' typo."""
    folded = str(status or "").strip().casefold()
    if not folded:
        return False
    if folded.isdigit():
        return True
    return "succes" in folded


def coerce_row_json(row_data: dict[str, Any]) -> dict[str, Any]:
    """Build classic AdvancedControls RowData; keep numeric-looking values as numbers."""
    out: dict[str, Any] = {}
    for key, value in (row_data or {}).items():
        text = str(value).strip()
        if key in INT_KEYS and text.isdigit():
            out[key] = int(text)
            continue
        if key in NUMERIC_KEYS:
            try:
                out[key] = float(text.replace(",", ".")) if text else text
                continue
            except ValueError:
                pass
        out[key] = text
    out.setdefault("Id", str(row_data.get("Id") or row_data.get("ID_Iesire") or ""))
    return out


def extract_created_ids(response: Any, row: dict[str, Any] | None = None) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key in ("ID_Iesire", "ID_Intrare", "ID_Unic", "OriginalID", "Cod", "NrDoc", "Id", "ID"):
        if row and row.get(key):
            ids[key] = str(row[key])
    if not isinstance(response, dict):
        return ids
    status = str(response.get("status") or "").strip()
    if status.isdigit():
        ids.setdefault("ID_Iesire", status)
        ids.setdefault("Id", status)
    data = response.get("data") or response.get("Data") or {}
    if isinstance(data, dict):
        canon_map = {
            "id_iesire": "ID_Iesire",
            "idiesire": "ID_Iesire",
            "id_intrare": "ID_Intrare",
            "id_unic": "ID_Unic",
            "originalid": "OriginalID",
            "cod": "Cod",
            "nrdoc": "NrDoc",
            "id": "Id",
        }
        for key, value in data.items():
            if value is None or str(value).strip() == "":
                continue
            norm = "".join(str(key).split()).casefold()
            canon = canon_map.get(norm, str(key))
            ids[canon] = str(value).strip()
    return ids


def created_record_id(response: Any, row: dict[str, Any] | None = None) -> str:
    """New grid PK from a create response. Never the request Cod / NrDoc / partner."""
    reserved: set[str] = set()
    if row:
        for key in ("Cod", "Client", "Furnizor", "NrDoc"):
            value = str(row.get(key) or "").strip()
            if value:
                reserved.add(value)
    ids = extract_created_ids(response, None)
    for key in ("ID_Iesire", "ID_Intrare", "ID_Unic", "OriginalID", "Id", "ID"):
        value = str(ids.get(key) or "").strip()
        if value and value not in reserved:
            return value
    return ""


def classify(
    body: Any,
    *,
    ok_http: bool = True,
    for_delete: bool = False,
    checked: bool = False,
) -> SagaResponse:
    if not ok_http:
        return SagaResponse(
            outcome="error",
            raw=body,
            message=status_text(body) or "HTTP error",
            ok_http=False,
        )
    if for_delete and (body is None or body == "" or body == {}):
        return SagaResponse(outcome="success", raw=body, ok_http=True)
    if isinstance(body, str) and "<html" in body[:200].casefold():
        return SagaResponse(outcome="error", raw=body, message="HTML error page", ok_http=True)
    if not isinstance(body, dict):
        if for_delete and ok_http:
            return SagaResponse(outcome="success", raw=body, ok_http=True)
        return SagaResponse(outcome="error", raw=body, message=status_text(body) or "Unexpected response", ok_http=True)

    if body.get("success") is False:
        return SagaResponse(outcome="error", raw=body, message=status_text(body) or "success=false", ok_http=True)

    kind = body.get("type")
    if kind == "Choice":
        return SagaResponse(
            outcome="needs_choice",
            raw=body,
            message=status_text(body),
            flag_id=str(body.get("flagId") or "").strip() or None,
            ok_http=True,
        )
    if kind == "Warning":
        return SagaResponse(outcome="warning", raw=body, message=status_text(body), ok_http=True)
    if kind == "Error":
        return SagaResponse(outcome="error", raw=body, message=status_text(body), ok_http=True)

    if body.get("errorCode") == "ValidateData":
        flags = [item for item in (body.get("validationFlags") or []) if isinstance(item, dict)]
        flag_id = None
        if flags:
            flag_id = str(flags[0].get("id") or flags[0].get("ID") or "").strip() or None
        return SagaResponse(
            outcome="needs_choice",
            raw=body,
            message=status_text(body) or "ValidateData",
            flag_id=flag_id,
            validation_flags=flags,
            ok_http=True,
        )

    status = str(body.get("status") or "").strip()
    if kind == "Validation" and status.isdigit():
        return SagaResponse(outcome="success", raw=body, new_id=status, ok_http=True)
    if kind == "Validation" and not checked:
        # First POST often returns Validation/"Succes." without persisting the row.
        return SagaResponse(outcome="needs_check", raw=body, message=status or "Validation", ok_http=True)
    if kind == "Validation":
        if status_is_success(status):
            return SagaResponse(outcome="success", raw=body, ok_http=True)
        return SagaResponse(outcome="needs_check", raw=body, message=status or "Validation", ok_http=True)

    if body.get("success") is True:
        return SagaResponse(outcome="success", raw=body, ok_http=True)
    if kind not in ("Warning", "Choice", "Error", "Validation") and body.get("success") is not False and "status" not in body:
        return SagaResponse(outcome="success", raw=body, ok_http=True)
    return SagaResponse(outcome="error", raw=body, message=status_text(body) or "Unclassified response", ok_http=True)


def _parse_response_body(response) -> Any:
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
    return parsed


def ajax(
    page,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    timeout: int = 60_000,
) -> dict[str, Any]:
    app_base = saga_session.app_base_url(page)
    absolute = urljoin(app_base.rstrip("/") + "/", path.lstrip("/"))
    headers = saga_session._auth_headers(page)
    try:
        if method.upper() == "GET":
            url = f"{absolute}?{urlencode(params or {})}" if params else absolute
            response = page.request.get(url, headers=headers, timeout=timeout)
        else:
            response = page.request.post(
                absolute,
                form=form or params or {},
                headers=headers,
                timeout=timeout,
            )
    except Exception as exc:
        return {
            "ok_http": False,
            "status": 0,
            "endpoint": absolute,
            "error": str(exc),
            "response": None,
            "request": {"method": method, "path": path, "params": params, "form": form},
        }
    parsed = _parse_response_body(response)
    return {
        "ok_http": bool(response.ok),
        "status": response.status,
        "endpoint": absolute,
        "response": parsed,
        "request": {"method": method, "path": path, "params": params, "form": form},
    }


def fetch_raw(
    page,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    timeout: int = 120_000,
    origin: str | None = None,
) -> dict[str, Any]:
    """HTTP call that keeps the raw body (exports / reports)."""
    app_base = (origin or saga_session.app_base_url(page)).rstrip("/")
    absolute = urljoin(app_base.rstrip("/") + "/", path.lstrip("/"))
    headers = saga_session._auth_headers(page)
    try:
        if method.upper() == "GET":
            url = f"{absolute}?{urlencode(params or {})}" if params else absolute
            response = page.request.get(url, headers=headers, timeout=timeout)
        else:
            response = page.request.post(
                absolute,
                form=form or params or {},
                headers=headers,
                timeout=timeout,
            )
    except Exception as exc:
        return {
            "ok_http": False,
            "status": 0,
            "endpoint": absolute,
            "error": str(exc),
            "body": b"",
            "content_type": "",
            "headers": {},
        }
    try:
        body = response.body()
    except Exception:
        body = b""
    if not isinstance(body, (bytes, bytearray)):
        body = str(body or "").encode("utf-8", errors="replace")
    return {
        "ok_http": bool(response.ok),
        "status": response.status,
        "endpoint": absolute,
        "body": bytes(body),
        "content_type": response.headers.get("content-type", ""),
        "headers": dict(response.headers),
        "error": None,
    }


def get_json(page, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    result = ajax(page, "GET", path, params=params, timeout=45_000)
    if result.get("status") == 0 and result.get("error"):
        return None
    if not result.get("ok_http"):
        return {
            "endpoint": result.get("endpoint"),
            "status": result.get("status"),
            "ok": False,
            "raw": str(result.get("response") or result.get("error") or "")[:500],
        }
    return {
        "endpoint": result.get("endpoint"),
        "status": result.get("status"),
        "ok": True,
        "body": result.get("response"),
    }


def check_flag(page, flag_id: str, *, status: str = "true") -> dict[str, Any]:
    return ajax(
        page,
        "GET",
        "Home/CheckFlag",
        params={"Id": flag_id, "Status": status, "Aux": ""},
    )


def _classic_form(
    page,
    row_data: dict[str, Any],
    *,
    checked: bool,
    uvf: Any = None,
) -> dict[str, str]:
    form: dict[str, str] = {
        "RowData": json.dumps(coerce_row_json(row_data), ensure_ascii=False, separators=(",", ":")),
        "_CHECKED": "true" if checked else "false",
        "SenderID": sender_id(page),
        "IsPaste": "false",
    }
    if uvf is None:
        form["uvf"] = ""
    else:
        form["uvf"] = json.dumps(uvf, ensure_ascii=False) if not isinstance(uvf, str) else uvf
    return form


def _ex_form(
    row_data: dict[str, Any],
    *,
    checked: bool = False,
    uvf: Any = None,
) -> dict[str, str]:
    form: dict[str, str] = {f"Data[{key}]": str(value) for key, value in row_data.items()}
    form["_CHECKED"] = "true" if checked else "false"
    form["IsPaste"] = "false"
    if uvf is not None:
        form["uvf"] = json.dumps(uvf, ensure_ascii=False) if not isinstance(uvf, str) else uvf
    return form


def _from_ajax(result: dict[str, Any], *, for_delete: bool = False, checked: bool = False) -> SagaResponse:
    classified = classify(
        result.get("response"),
        ok_http=bool(result.get("ok_http")),
        for_delete=for_delete,
        checked=checked,
    )
    classified.endpoint = str(result.get("endpoint") or "")
    classified.status = int(result.get("status") or 0)
    classified.ok_http = bool(result.get("ok_http"))
    classified.request = result.get("request") if isinstance(result.get("request"), dict) else None
    classified.chain = [result]
    if result.get("error") and classified.outcome == "error" and not classified.message:
        classified.message = str(result.get("error"))
    return classified


def post_with_handshake(
    page,
    path: str,
    *,
    row_data: dict[str, Any] | None = None,
    style: WriteStyle = "classic",
    allow_choices: bool = False,
    operation: WriteOp = "create",
    uvf: Any = None,
) -> SagaResponse:
    """POST create/edit with _CHECKED / uvf handshake. Max 3 round trips."""
    data = dict(row_data or {})
    if style == "classic":
        first = ajax(page, "POST", path, form=_classic_form(page, data, checked=False, uvf=uvf))
    else:
        first = ajax(page, "POST", path, form=_ex_form(data, checked=False, uvf=uvf), timeout=45_000)
    resp = _from_ajax(first, for_delete=False)
    resp.via = f"{style}_{operation}"

    if resp.outcome == "success":
        if not resp.new_id:
            resp.new_id = created_record_id(resp.raw, data) or None
        return resp

    if resp.outcome == "needs_choice":
        if not allow_choices:
            return resp
        if style == "classic":
            flag = resp.flag_id or "Choice"
            choice_uvf = [{"FlagId": flag, "Value": "Yes"}]
            second = ajax(page, "POST", path, form=_classic_form(page, data, checked=True, uvf=choice_uvf))
        else:
            flags: list[dict[str, str]] = []
            for item in resp.validation_flags:
                flag_id = item.get("id") or item.get("ID")
                if flag_id:
                    flags.append({"id": str(flag_id), "userChoice": "Yes"})
            if not flags and resp.flag_id:
                flags = [{"id": resp.flag_id, "userChoice": "Yes"}]
            second = ajax(page, "POST", path, form=_ex_form(data, checked=False, uvf=flags), timeout=45_000)
        classified = classify(
            second.get("response"),
            ok_http=bool(second.get("ok_http")),
            checked=True,
        )
        classified.via = f"{style}_{operation}_choice"
        classified.chain = [first, second]
        classified.endpoint = str(second.get("endpoint") or "")
        classified.status = int(second.get("status") or 0)
        classified.ok_http = bool(second.get("ok_http"))
        classified.request = second.get("request") if isinstance(second.get("request"), dict) else None
        if classified.outcome == "success":
            classified.new_id = classified.new_id or created_record_id(classified.raw, data) or None
        return classified

    if resp.outcome == "needs_check":
        if style == "classic":
            second = ajax(page, "POST", path, form=_classic_form(page, data, checked=True, uvf=uvf))
        else:
            second = ajax(page, "POST", path, form=_ex_form(data, checked=True, uvf=uvf), timeout=45_000)
        classified = classify(
            second.get("response"),
            ok_http=bool(second.get("ok_http")),
            checked=True,
        )
        classified.via = f"{style}_{operation}_checked"
        classified.chain = [first, second]
        classified.endpoint = str(second.get("endpoint") or "")
        classified.status = int(second.get("status") or 0)
        classified.ok_http = bool(second.get("ok_http"))
        classified.request = second.get("request") if isinstance(second.get("request"), dict) else None
        parsed = classified.raw
        if classified.outcome == "success":
            classified.new_id = classified.new_id or created_record_id(parsed, data) or None
            return classified
        # Classic IesiriValuta: Validation + numeric/"Succes" after checked.
        if (
            second.get("ok_http")
            and isinstance(parsed, dict)
            and parsed.get("type") == "Validation"
            and not str(parsed.get("status") or "").strip().endswith("?")
            and "Continuam" not in str(parsed.get("status") or "")
        ):
            status = str(parsed.get("status") or "").strip()
            if status_is_success(status):
                classified.outcome = "success"
                classified.new_id = status if status.isdigit() else classified.new_id
                classified.message = None
                return classified
        return classified

    return resp


def _delete_ex(page, path: str, pk: str, *, allow_choices: bool) -> SagaResponse:
    form = {"ID": pk, "UserValidationFlags": "[]"}
    first = ajax(page, "POST", path, form=form, timeout=45_000)
    resp = _from_ajax(first, for_delete=True)
    resp.via = "api_ex"
    if resp.outcome == "success":
        return resp
    if resp.outcome == "needs_choice" and resp.validation_flags:
        if not allow_choices:
            return resp
        flags = []
        for item in resp.validation_flags:
            flag_id = item.get("id") or item.get("ID")
            if flag_id:
                flags.append({"ID": str(flag_id), "UserChoice": "Yes"})
        second = ajax(
            page,
            "POST",
            path,
            form={"ID": pk, "UserValidationFlags": json.dumps(flags, ensure_ascii=False)},
            timeout=45_000,
        )
        classified = classify(
            second.get("response"),
            ok_http=bool(second.get("ok_http")),
            for_delete=True,
            checked=True,
        )
        classified.via = "api_ex"
        classified.chain = [first, second]
        classified.endpoint = str(second.get("endpoint") or "")
        classified.status = int(second.get("status") or 0)
        classified.ok_http = bool(second.get("ok_http"))
        return classified
    return resp


def _delete_classic_once(
    page,
    method: str,
    path: str,
    form: dict[str, str],
) -> dict[str, Any]:
    if method == "GET":
        return ajax(page, "GET", path, params=form, timeout=45_000)
    return ajax(page, "POST", path, form=form, timeout=45_000)


def _delete_classic(page, path: str, pk: str, *, allow_choices: bool) -> SagaResponse:
    sender = sender_id(page)
    last = SagaResponse(outcome="error", message="Classic delete failed.")
    chain: list[dict[str, Any]] = []
    for method in ("POST", "GET"):
        first_form = {"Id": pk, "_CHECKED": "false", "SenderID": sender}
        first = _delete_classic_once(page, method, path, first_form)
        chain.append(first)
        classified = classify(first.get("response"), ok_http=bool(first.get("ok_http")), for_delete=True)
        classified.via = f"api_classic_{method.lower()}"
        classified.chain = list(chain)
        classified.endpoint = str(first.get("endpoint") or "")
        classified.status = int(first.get("status") or 0)
        classified.ok_http = bool(first.get("ok_http"))
        if classified.outcome == "success":
            return classified
        if classified.outcome == "needs_choice":
            if not allow_choices:
                return classified
            flag = classified.flag_id
            if flag:
                check_flag(page, flag)
            checked_form = {"Id": pk, "_CHECKED": "true", "SenderID": sender}
            if flag:
                checked_form["Type"] = flag
            second = _delete_classic_once(page, method, path, checked_form)
            chain.append(second)
            done = classify(
                second.get("response"),
                ok_http=bool(second.get("ok_http")),
                for_delete=True,
                checked=True,
            )
            done.via = f"api_classic_{method.lower()}"
            done.chain = list(chain)
            done.endpoint = str(second.get("endpoint") or "")
            done.status = int(second.get("status") or 0)
            done.ok_http = bool(second.get("ok_http"))
            if done.outcome == "success":
                return done
            last = done
            continue
        if classified.outcome == "needs_check" or (
            isinstance(first.get("response"), dict) and first["response"].get("type") == "Validation"
        ):
            second = _delete_classic_once(
                page,
                method,
                path,
                {"Id": pk, "_CHECKED": "true", "SenderID": sender},
            )
            chain.append(second)
            done = classify(
                second.get("response"),
                ok_http=bool(second.get("ok_http")),
                for_delete=True,
                checked=True,
            )
            done.via = f"api_classic_{method.lower()}"
            done.chain = list(chain)
            done.endpoint = str(second.get("endpoint") or "")
            done.status = int(second.get("status") or 0)
            done.ok_http = bool(second.get("ok_http"))
            if done.outcome == "success":
                return done
            last = done
            continue
        last = classified
    last.chain = chain
    return last


def delete_with_handshake(
    page,
    path: str,
    pk: str,
    *,
    allow_choices: bool = False,
) -> dict[str, Any]:
    """Ex-style delete first, then classic POST-then-GET _CHECKED handshake."""
    ex = _delete_ex(page, path, pk, allow_choices=allow_choices)
    if ex.ok:
        payload = ex.as_dict()
        payload["ok"] = True
        payload["via"] = ex.via or "api_ex"
        return payload
    classic = _delete_classic(page, path, pk, allow_choices=allow_choices)
    if classic.ok:
        payload = classic.as_dict()
        payload["ok"] = True
        payload["via"] = classic.via or "api_classic"
        return payload
    return {
        "ok": False,
        "error": classic.message or ex.message or "Delete failed.",
        "response": classic.raw if classic.raw is not None else ex.raw,
        "via": classic.via or ex.via or "api",
        "endpoint": classic.endpoint or ex.endpoint,
        "attempts": (ex.chain or []) + (classic.chain or []),
        "chain": (ex.chain or []) + (classic.chain or []),
    }
