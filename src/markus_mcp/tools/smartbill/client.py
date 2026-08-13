from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from markus_mcp.tools.smartbill.credentials import SmartbillCredentials, load_credentials

PUBLIC_BASE = "https://ws.smartbill.ro/SBORO/api"


class SmartbillApiError(RuntimeError):
    def __init__(self, message: str, *, http_status: int | None = None, body: str = ""):
        super().__init__(message)
        self.http_status = http_status
        self.body = body


def _headers(creds: SmartbillCredentials) -> dict[str, str]:
    auth = base64.b64encode(f"{creds.username}:{creds.token}".encode("utf-8")).decode("ascii")
    return {
        "Accept": "application/json",
        "Authorization": f"Basic {auth}",
    }


def public_get(path: str, params: dict[str, str] | None = None, *, creds: SmartbillCredentials | None = None) -> dict[str, Any]:
    creds = creds or load_credentials()
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v})
    url = f"{PUBLIC_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(url, headers=_headers(creds), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            http_status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SmartbillApiError(
            f"SmartBill API HTTP {exc.code} on {path}",
            http_status=exc.code,
            body=body[:500],
        ) from exc
    except urllib.error.URLError as exc:
        raise SmartbillApiError(f"Could not reach SmartBill API: {exc.reason}") from exc

    parsed: Any = raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        pass
    return {"ok": http_status == 200, "http_status": http_status, "data": parsed, "url": url}


def get_series(*, creds: SmartbillCredentials | None = None) -> dict[str, Any]:
    creds = creds or load_credentials()
    params = {"cif": creds.cif} if creds.cif else {}
    return public_get("/series", params, creds=creds)
