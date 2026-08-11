from __future__ import annotations

import os
from typing import Any

from markus_mcp import __version__
from markus_mcp.paths import credentials_file, data_dir, markus_home


def health_check() -> dict[str, Any]:
    transport = os.getenv("MARKUS_MCP_TRANSPORT", "stdio").strip().lower()
    if transport in {"http", "streamable-http"}:
        transport_name = "streamable-http"
        endpoint = "/mcp"
    else:
        transport_name = "stdio"
        endpoint = None
    return {
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
    }
