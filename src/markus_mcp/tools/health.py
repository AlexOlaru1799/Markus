from __future__ import annotations

import os
from typing import Any

from markus_mcp import __version__
from markus_mcp.paths import credentials_file, data_dir, markus_home
from markus_mcp.source_info import fingerprint
from markus_mcp.tools.smartbill.credentials import load_credentials as load_smartbill_credentials


def health_check() -> dict[str, Any]:
    transport = os.getenv("MARKUS_MCP_TRANSPORT", "stdio").strip().lower()
    if transport in {"http", "streamable-http"}:
        transport_name = "streamable-http"
        endpoint = "/mcp"
    else:
        transport_name = "stdio"
        endpoint = None
    payload = {
        "status": "ok",
        "server": "markus-mcp",
        "version": __version__,
        "transport": transport_name,
        "endpoint": endpoint,
        "markus_home": str(markus_home()),
        "data_dir": str(data_dir()),
        "credentials_file": str(credentials_file()),
        "whatsapp_web_tools": True,
        "saga_web_tools": True,
        "smartbill_tools": True,
        "smartbill_token_configured": load_smartbill_credentials().token_configured,
        "smartbill_saga_xml": True,
    }
    payload.update(fingerprint())
    return payload
