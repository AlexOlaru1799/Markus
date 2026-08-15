from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.mcpserver.server import MCPServer
from mcp_types import ToolAnnotations

from markus_mcp import __version__
from markus_mcp.tools.catalog import tool_catalog_as_dicts
from markus_mcp.tools.health import health_check as run_health_check
from markus_mcp.tools import whatsapp_web
from markus_mcp.tools.saga import partners as saga_partners
from markus_mcp.tools.saga import iesiri_valuta as saga_iesiri_valuta
from markus_mcp.tools.saga import import_date as saga_import_date
from markus_mcp.tools.saga import iesiri as saga_iesiri
from markus_mcp.tools.saga import jurnal_banca_import as saga_jurnal_banca_import
from markus_mcp.tools.saga import wipe as saga_wipe
from markus_mcp.tools.saga import session as saga_session
from markus_mcp.tools import smartbill as smartbill_tools


HOST = os.getenv("MARKUS_MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MARKUS_MCP_PORT", "8000"))
TRANSPORT = os.getenv("MARKUS_MCP_TRANSPORT", "stdio").strip().lower()


def active_transport() -> str:
    if TRANSPORT in {"http", "streamable-http"}:
        return "streamable-http"
    return "stdio"


mcp = MCPServer(
    name="markus-mcp",
    version=__version__,
    instructions=(
        "Use health_check when a Markus MCP tool call fails. Use list_tools when the "
        "user asks what Markus can do. "
        "WhatsApp pairing: call whatsapp_web_pair (returns quickly). Tell the user to "
        "open the returned screenshot_path and scan the QR. The browser stays open in "
        "the background and the QR image refreshes automatically. Then poll "
        "whatsapp_web_status until paired=true. Do not wait inside a long-running pair call. "
        "Sending messages: call send_whatsapp_message with to_name and message and "
        "confirm_send=false first. Recipient names must match a WhatsApp chat/contact "
        "exactly (case-insensitive); never send to a near match. Show the preview to the "
        "user and only call again with confirm_send=true after they explicitly confirm "
        "(for example 'yes, send it'). Optional to_phone_number is an escape hatch when "
        "the user provides a number with country code. "
        "SAGA WEB: credentials are read from private.data (never ask the user to paste "
        "passwords into chat). Call saga_login first. Prefer the 3-month browser trust: "
        "if needs_browser_authorization=true, tell the user to click 'Autorizează browser' "
        "in the SAGA email (not 'Autentificare fără autorizare'), then saga_login again. "
        "Only use saga_login(allow_otp_without_authorization=true) when the user explicitly "
        "wants a one-time OTP path. If needs_otp=true, ask for the 6-digit email code and "
        "call saga_submit_otp. Keep ~/.markus/data/saga-session; do not call saga_reset_session "
        "with delete_profile=true unless asked. Partner/client tools: saga_list_partners, "
        "saga_search_partners, saga_get_partner, saga_create_partner, saga_update_partner, "
        "saga_remove_partner. FX sales (IesiriValuta): saga_iesiri_valuta_fields, "
        "saga_add_iesiri_valuta (header + lines). "
        "Use saga_partner_fields / saga_iesiri_valuta_fields to see writable columns. For create/update, "
        "pass only fields the user specified — never invent optional values. Mutations "
        "(create/update/remove/add_iesiri_valuta/import_xml/import_iesiri_xml/import_incasari_xml/wipe_data) require confirm_write=false preview first, then "
        "confirm_write=true after explicit user OK. "
        "PDF FX imports: agent reads the PDF, ensures partner exists, then saga_add_iesiri_valuta; "
        "WhatsApp notify per the import-fx-invoice-to-saga skill. "
        "XML Import date: saga_import_xml with xml_path to a SAGA Facturi XML "
        "(typically F_<cif>_<dd>_<mm>_<yyyy>.xml). Opens "
        "https://web2.sagasoft.ro/sagac/ImportDate, uploads, then ImportFactura. "
        "Same confirm_write preview then explicit user OK. Use this for purchases "
        "(Intrări valută). RON sales Ieșiri Facturi XML (Furnizor = your firm, "
        "ClientNume/ClientCod = customers, extra <Cont>/<TVAProc>): saga_import_iesiri_xml. "
        "Creates Iesiri/Create_Iesiri so NrDoc stays as FacturaNumar; existing NrDoc is skipped. "
        "Do not send sales Ieșiri XML to saga_import_xml. "
        "Încasări/Plăți XML (I_<dd>_<mm>_<yyyy>.xml or P_…, root <Incasari>/<Plati>): "
        "saga_import_incasari_xml. Opens Jurnal de Bancă, uploads via Import extrase "
        "(RegistruCasa/IncarcaExtras), fills treasury account (from XML Cont or account=), "
        "sets each row's client/supplier from unpaid Ieșiri/Intrări matching <FacturaNumar> "
        "(or from partner= if the user named one), clicks SAGA's Asociere automata button, then Accept. "
        "Same confirm_write preview then explicit user OK. "
        "Do not send I_/P_ files to saga_import_xml. "
        "Wipe current firm data: saga_wipe_data. Default targets are Jurnal de bancă "
        "(clears Import extrase staging, then day entries before day headers), "
        "Intrări valută, Intrări, Ieșiri valută, Ieșiri (receipt allocations and "
        "lines before headers), then Furnizori and Clienți. "
        "Does not wipe plan de conturi, salarii, închidere lună, or company config. "
        "Preview shows firm name, interval, and counts — only confirm_write=true after "
        "the user explicitly OK's that firm. Optional targets= comma-separated keys. "
        "SmartBill: token (and optional username/CIF) from private.data. "
        "Call smartbill_status to verify. Username falls back to saga_username. "
        "Supplier invoices (Documente furnizori): smartbill_list_supplier_invoices then "
        "smartbill_export_supplier_invoices_xls then smartbill_invoices_to_saga_xml. "
        "Pass date_from/date_to as YYYY-MM-DD or period=this_month|last_month. "
        "The XML converter keeps rows with NIR and skips Romanian CIF (RO…). "
        "To load that XML into SAGA, saga_import_xml after the user confirms. "
        "Cloud UI login uses smartbill_password or saga_password."
    ),
)


@mcp.tool(
    title="Health check",
    description=(
        "Ping the Markus MCP server and confirm it is reachable. Use this when "
        "another Markus MCP tool fails or before debugging connectivity."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def health_check() -> dict[str, Any]:
    return run_health_check()


@mcp.tool(
    title="List tools",
    description="Show the tools currently exposed by the Markus MCP server.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def list_tools() -> dict[str, Any]:
    tools = tool_catalog_as_dicts()
    return {
        "server": "markus-mcp",
        "version": __version__,
        "tool_count": len(tools),
        "tools": tools,
    }


@mcp.tool(
    title="WhatsApp Web status",
    description="Check whether the single persisted WhatsApp Web session is paired and ready.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def whatsapp_web_status() -> dict[str, Any]:
    return whatsapp_web.status()


@mcp.tool(
    title="WhatsApp Web pair",
    description=(
        "Open WhatsApp Web, keep the browser session alive, and return a QR screenshot "
        "path immediately. Tell the user to open screenshot_path and scan it. Then poll "
        "whatsapp_web_status until paired=true. Does not block waiting for the scan."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def whatsapp_web_pair(timeout_sec: int = 180) -> dict[str, Any]:
    return whatsapp_web.pair(timeout_sec=timeout_sec)


@mcp.tool(
    title="WhatsApp Web pairing screenshot",
    description=(
        "Deprecated. Prefer whatsapp_web_pair. Takes a short live wait and returns a QR "
        "screenshot path; screenshot-only pairing after the browser closes cannot succeed."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def whatsapp_web_pairing_screenshot() -> dict[str, Any]:
    return whatsapp_web.pairing_screenshot()


@mcp.tool(
    title="WhatsApp Web reset session",
    description=(
        "Close the live WhatsApp browser session. Set delete_profile=true to wipe the "
        "persisted profile so the next pair starts fresh."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
)
def whatsapp_web_reset_session(delete_profile: bool = False) -> dict[str, Any]:
    return whatsapp_web.reset_session(delete_profile=delete_profile)


@mcp.tool(
    title="Send WhatsApp message",
    description=(
        "Send a WhatsApp message through the paired Web session. Prefer to_name with an "
        "exact chat/contact title match (case-insensitive). Never send on a near match. "
        "Always call first with confirm_send=false to preview; only after explicit user "
        "confirmation call again with confirm_send=true. Optional to_phone_number requires "
        "country code."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def send_whatsapp_message(
    message: str,
    to_name: str | None = None,
    to_phone_number: str | None = None,
    confirm_send: bool = False,
) -> dict[str, Any]:
    return whatsapp_web.send_message(
        message=message,
        to_name=to_name,
        to_phone_number=to_phone_number,
        confirm_send=confirm_send,
    )


@mcp.tool(
    title="SAGA status",
    description="Check whether the SAGA WEB browser session is logged in and firm-ready.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_status() -> dict[str, Any]:
    return saga_session.status()


@mcp.tool(
    title="SAGA login",
    description=(
        "Log in to SAGA WEB using credentials from private.data. "
        "Default: wait for 3-month browser authorization via email "
        "(needs_browser_authorization=true). Set allow_otp_without_authorization=true "
        "only if the user explicitly wants the one-time OTP path."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_login(allow_otp_without_authorization: bool = False) -> dict[str, Any]:
    return saga_session.login(
        allow_otp_without_authorization=allow_otp_without_authorization
    )

@mcp.tool(
    title="SAGA submit OTP",
    description="Submit the 6-digit SAGA email OTP code after saga_login returns needs_otp=true.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_submit_otp(code: str) -> dict[str, Any]:
    return saga_session.submit_otp(code)


@mcp.tool(
    title="SAGA reset session",
    description="Close the SAGA browser session. Set delete_profile=true to wipe persisted cookies/profile.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
)
def saga_reset_session(delete_profile: bool = False) -> dict[str, Any]:
    return saga_session.reset_session(delete_profile=delete_profile)


@mcp.tool(
    title="SAGA list partners",
    description="List SAGA partners/clients with optional text filter and pagination.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_list_partners(page: int = 1, page_size: int = 50, query: str | None = None) -> dict[str, Any]:
    return saga_partners.list_partners(page=page, page_size=page_size, query=query)


@mcp.tool(
    title="SAGA search partners",
    description="Search SAGA partners/clients by name, code, or CUI.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_search_partners(query: str, limit: int = 50) -> dict[str, Any]:
    return saga_partners.search_partners(query, limit=limit)


@mcp.tool(
    title="SAGA get partner",
    description="Fetch one SAGA partner by exact id/cod/CUI/name match.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_get_partner(partner_id: str) -> dict[str, Any]:
    return saga_partners.get_partner(partner_id)


@mcp.tool(
    title="SAGA partner fields",
    description=(
        "List writable SAGA Clienti/partner fields and aliases. Use before create/update "
        "so only user-specified fields are sent."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_partner_fields() -> dict[str, Any]:
    return saga_partners.partner_field_catalog()


@mcp.tool(
    title="SAGA create partner",
    description=(
        "Create a SAGA partner/client. Pass only fields the user specified (see "
        "saga_partner_fields). Call first with confirm_write=false to preview, then again "
        "with confirm_write=true after explicit user confirmation."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_create_partner(fields: dict[str, Any], confirm_write: bool = False) -> dict[str, Any]:
    return saga_partners.create_partner(fields, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA update partner",
    description=(
        "Update a SAGA partner/client by exact id/name. Pass only fields the user wants "
        "changed; unspecified fields stay unchanged. Preview with confirm_write=false, then "
        "confirm_write=true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_update_partner(
    partner_id: str,
    fields: dict[str, Any],
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_partners.update_partner(partner_id, fields, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA remove partner",
    description=(
        "Remove a SAGA partner/client by exact id/cod/CUI/name. Call first with "
        "confirm_write=false to preview the matched row, then again with "
        "confirm_write=true after explicit user confirmation."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_remove_partner(partner_id: str, confirm_write: bool = False) -> dict[str, Any]:
    return saga_partners.delete_partner(partner_id, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA IesiriValuta fields",
    description=(
        "List writable IesiriValuta (foreign-currency sales) header and line fields/aliases. "
        "Use before saga_add_iesiri_valuta so only user-specified fields are sent."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_iesiri_valuta_fields() -> dict[str, Any]:
    return saga_iesiri_valuta.fx_invoice_field_catalog()


@mcp.tool(
    title="SAGA add IesiriValuta",
    description=(
        "Add a foreign-currency sales document on IesiriValuta. Pass header fields plus a "
        "lines array. Each line requires Cont (e.g. 704/707). Preview with confirm_write=false, "
        "then confirm_write=true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_add_iesiri_valuta(
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_iesiri_valuta.create_fx_invoice(header, lines, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA import XML",
    description=(
        "Upload a SAGA Facturi XML on Import date "
        "(https://web2.sagasoft.ro/sagac/ImportDate) and import it. "
        "Preview with confirm_write=false, then confirm_write=true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_import_xml(xml_path: str, confirm_write: bool = False) -> dict[str, Any]:
    return saga_import_date.import_xml(xml_path, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA import Ieșiri XML",
    description=(
        "Create RON Ieșiri (sales invoices) from a SAGA Facturi XML "
        "(F_*.xml with ClientNume/ClientCod). Posts Iesiri/Create_Iesiri so "
        "NrDoc matches FacturaNumar. Existing NrDoc values are skipped. "
        "Preview with confirm_write=false, then confirm_write=true after explicit user OK. "
        "Not Import date — use saga_import_xml for purchases. "
        "Not I_/P_ bank XML — use saga_import_incasari_xml for those."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_import_iesiri_xml(xml_path: str, confirm_write: bool = False) -> dict[str, Any]:
    return saga_iesiri.import_iesiri_xml(xml_path, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA import încasări XML",
    description=(
        "Upload a SAGA Încasări or Plăți XML (I_*.xml / P_*.xml) on Jurnal de Bancă "
        "Import extrase (https://web2.sagasoft.ro/sagac/JurnalDeBanca), set each row's "
        "client/supplier from unpaid Ieșiri/Intrări matching <FacturaNumar>, associate "
        "via SAGA DisplayData(codFactura), then Accept. Preview with confirm_write=false, then "
        "confirm_write=true after explicit user OK. Optional partner= forces one "
        "client/supplier on every row. Optional account overrides XML <Cont>. "
        "asociere=true by default."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_import_incasari_xml(
    xml_path: str,
    confirm_write: bool = False,
    partner: str = "",
    account: str = "",
    asociere: bool = True,
) -> dict[str, Any]:
    return saga_jurnal_banca_import.import_incasari_xml(
        xml_path,
        confirm_write=confirm_write,
        partner=partner,
        account=account,
        asociere=asociere,
    )


@mcp.tool(
    title="SAGA wipe data",
    description=(
        "Permanently delete SAGA rows on the connected firm: Jurnal de bancă "
        "(Import extrase cache, then day entries, then day headers), Intrări / "
        "Ieșiri (with and without valută; allocations and lines first), then "
        "Furnizori and Clienți. Does not wipe "
        "plan de conturi, salarii, închidere lună, or config. Preview with "
        "confirm_write=false, then confirm_write=true after explicit user OK. "
        "Optional targets is a comma-separated list of: "
        "jurnal_banca,intrari_valuta,intrari,iesiri_valuta,iesiri,furnizori,clienti."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_wipe_data(confirm_write: bool = False, targets: str = "") -> dict[str, Any]:
    return saga_wipe.wipe_data(confirm_write=confirm_write, targets=targets)


@mcp.tool(
    title="SmartBill status",
    description=(
        "Check whether the SmartBill API token is stored in private.data and, when "
        "email and CIF are also present, probe GET /series."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def smartbill_status() -> dict[str, Any]:
    return smartbill_tools.status()


@mcp.tool(
    title="SmartBill list supplier invoices",
    description=(
        "List SmartBill Documente furnizori (supplier invoices) for a period. "
        "Pass date_from and date_to as YYYY-MM-DD, or period=this_month / last_month."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def smartbill_list_supplier_invoices(
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
    section: str = "all",
    limit: int = 200,
) -> dict[str, Any]:
    return smartbill_tools.list_supplier_invoices(
        date_from=date_from,
        date_to=date_to,
        period=period,
        section=section,
        limit=limit,
    )


@mcp.tool(
    title="SmartBill export supplier invoices Excel",
    description=(
        "Export SmartBill Documente furnizori for a period to Excel under ~/.markus/data/smartbill/. "
        "Prefers SmartBill's own Export Excel; otherwise writes .xlsx from the listed rows."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def smartbill_export_supplier_invoices_xls(
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
    section: str = "all",
) -> dict[str, Any]:
    return smartbill_tools.export_supplier_invoices_xls(
        date_from=date_from,
        date_to=date_to,
        period=period,
        section=section,
    )


@mcp.tool(
    title="SmartBill invoices to SAGA XML",
    description=(
        "Convert a SmartBill Documente furnizori spreadsheet into SAGA Facturi XML. "
        "Pass xls_path to convert an existing file, or period/date_from/date_to to export "
        "first then convert. Keeps rows with NIR; skips invoices whose CIF starts with RO."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def smartbill_invoices_to_saga_xml(
    xls_path: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
    section: str = "all",
) -> dict[str, Any]:
    return smartbill_tools.invoices_to_saga_xml(
        xls_path=xls_path,
        date_from=date_from,
        date_to=date_to,
        period=period,
        section=section,
    )


def main() -> None:
    import sys

    argv = sys.argv[1:]
    if "--set-credentials" in argv:
        from markus_mcp.bootstrap import set_credentials_cli

        raise SystemExit(set_credentials_cli())

    if "--register-cursor" in argv or "--setup" in argv:
        from markus_mcp.bootstrap import bootstrap
        from markus_mcp.cursor_install import merge_markus_mcp

        install_browser = "--skip-browser" not in argv
        setup_result = bootstrap(install_browser=install_browser)
        binary = None
        if getattr(sys, "frozen", False):
            from pathlib import Path

            binary = Path(sys.executable)
        merge = merge_markus_mcp(binary=binary)
        print(json.dumps({"setup": setup_result, "cursor": merge}, indent=2))
        return

    if active_transport() == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host=HOST,
            port=PORT,
            streamable_http_path="/mcp",
        )
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

