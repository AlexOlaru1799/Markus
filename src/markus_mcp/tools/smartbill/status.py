from __future__ import annotations

import json
from typing import Any

from markus_mcp.tools.smartbill.client import SmartbillApiError, get_series
from markus_mcp.tools.smartbill.credentials import load_credentials


def status() -> dict[str, Any]:
    creds = load_credentials()
    result: dict[str, Any] = {
        "configured": creds.token_configured,
        "token_configured": creds.token_configured,
        "username_configured": creds.username_configured,
        "cif_configured": creds.cif_configured,
        "password_configured": creds.password_configured,
        "credentials_file": creds.source_file,
        "details": "",
    }
    if not creds.token_configured:
        result["details"] = (
            "SmartBill API token is not set. Add smartbill_token in private.data "
            "or rerun the installer."
        )
        return result
    if not creds.username_configured:
        result["details"] = (
            "SmartBill token is stored, but no email is set. Add smartbill_username "
            "or saga_username in private.data (Basic Auth uses email:token)."
        )
        return result
    if not creds.cif_configured:
        result["ok"] = True
        result["details"] = (
            "SmartBill token is stored. Add smartbill_cif (firm CUI) in private.data "
            "to probe GET /series. Supplier-invoice list/export uses the Cloud UI "
            "(needs smartbill_password or saga_password)."
        )
        return result

    try:
        payload = get_series(creds=creds)
    except SmartbillApiError as exc:
        result["ok"] = False
        result["http_status"] = exc.http_status
        if exc.http_status in {401, 403}:
            result["details"] = (
                "SmartBill API rejected the request. Check smartbill_token, "
                "email, and smartbill_cif in private.data."
            )
        else:
            result["details"] = str(exc)
        return result

    data = payload.get("data")
    series_count: int | None = None
    if isinstance(data, list):
        series_count = len(data)
    elif isinstance(data, dict):
        for key in ("list", "series", "numberList"):
            value = data.get(key)
            if isinstance(value, list):
                series_count = len(value)
                break
    elif isinstance(data, str):
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                series_count = len(parsed)
        except json.JSONDecodeError:
            pass

    result["ok"] = bool(payload.get("ok"))
    result["http_status"] = payload.get("http_status")
    if series_count is not None:
        result["series_count"] = series_count
    result["details"] = (
        "SmartBill API reachable with the stored token."
        if result["ok"]
        else f"SmartBill API returned HTTP {payload.get('http_status')}."
    )
    return result
