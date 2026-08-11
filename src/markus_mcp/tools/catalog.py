from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolInfo:
    name: str
    title: str
    description: str
    read_only: bool


TOOL_CATALOG: tuple[ToolInfo, ...] = (
    ToolInfo(
        name="health_check",
        title="Health check",
        description=(
            "Ping the Markus MCP server and confirm it is reachable. "
            "Use this when another Markus MCP tool fails or before debugging connectivity."
        ),
        read_only=True,
    ),
    ToolInfo(
        name="list_tools",
        title="List tools",
        description="Show the tools currently exposed by the Markus MCP server.",
        read_only=True,
    ),
    ToolInfo(
        name="whatsapp_web_status",
        title="WhatsApp Web status",
        description="Check whether the single persisted WhatsApp Web session is paired and ready.",
        read_only=True,
    ),
    ToolInfo(
        name="whatsapp_web_pair",
        title="WhatsApp Web pair",
        description=(
            "Open WhatsApp Web, return a QR screenshot immediately, and keep the "
            "browser alive in the background. Then poll whatsapp_web_status."
        ),
        read_only=False,
    ),
    ToolInfo(
        name="whatsapp_web_pairing_screenshot",
        title="WhatsApp Web pairing screenshot",
        description="Deprecated. Prefer whatsapp_web_pair for live QR pairing.",
        read_only=False,
    ),
    ToolInfo(
        name="whatsapp_web_reset_session",
        title="WhatsApp Web reset session",
        description="Close the live browser session; optionally delete the persisted profile.",
        read_only=False,
    ),
    ToolInfo(
        name="send_whatsapp_message",
        title="Send WhatsApp message",
        description=(
            "Send via exact chat name match or phone number. "
            "Requires confirm_send=true after an explicit user confirmation."
        ),
        read_only=False,
    ),
    ToolInfo(
        name="saga_status",
        title="SAGA status",
        description="Check whether the SAGA WEB session is logged in and firm-ready.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_login",
        title="SAGA login",
        description="Log in to SAGA WEB using private.data credentials.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_submit_otp",
        title="SAGA submit OTP",
        description="Submit the 6-digit SAGA email OTP code.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_reset_session",
        title="SAGA reset session",
        description="Close the SAGA browser session; optionally delete the profile.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_list_partners",
        title="SAGA list partners",
        description="List SAGA partners/clients with optional filter and pagination.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_search_partners",
        title="SAGA search partners",
        description="Search SAGA partners/clients by name, code, or CUI.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_get_partner",
        title="SAGA get partner",
        description="Fetch one SAGA partner by exact id/cod/CUI/name.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_partner_fields",
        title="SAGA partner fields",
        description="List writable Clienti fields/aliases; only user-specified fields are written.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_create_partner",
        title="SAGA create partner",
        description="Create a partner/client with only user-specified fields; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_update_partner",
        title="SAGA update partner",
        description="Update only user-specified partner fields; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_remove_partner",
        title="SAGA remove partner",
        description="Remove a partner/client by exact id; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_iesiri_valuta_fields",
        title="SAGA IesiriValuta fields",
        description="List writable IesiriValuta header/line fields and aliases.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_add_iesiri_valuta",
        title="SAGA add IesiriValuta",
        description="Add IesiriValuta foreign-currency sales doc (header + lines); requires confirm_write.",
        read_only=False,
    ),
)


def tool_catalog_as_dicts() -> list[dict[str, object]]:
    return [asdict(tool) for tool in TOOL_CATALOG]
