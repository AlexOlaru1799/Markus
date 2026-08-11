from __future__ import annotations

from typing import Any

from markus_mcp import __version__


def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "server": "markus-mcp",
        "version": __version__,
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "whatsapp_web_tools": True,
        "saga_web_tools": True,
    }
