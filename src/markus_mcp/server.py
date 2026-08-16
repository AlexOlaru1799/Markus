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
from markus_mcp.tools.saga import context as saga_context_mod
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga import reads as saga_reads
from markus_mcp.tools.saga import lookups as saga_lookups
from markus_mcp.tools.saga import exports as saga_exports
from markus_mcp.tools.saga import reports as saga_reports
from markus_mcp.tools.saga import nomenclator as saga_nomenclator
from markus_mcp.tools.saga import invoices as saga_invoices
from markus_mcp.tools.saga import bank as saga_bank
from markus_mcp.tools.saga import efactura as saga_efactura
from markus_mcp.tools.saga import validate_doc as saga_validate_doc
from markus_mcp.tools.saga import declarations as saga_declarations
from markus_mcp.tools.saga.documents.parse_facturi_xml import parse_facturi_xml
from markus_mcp.tools.saga.documents.parse_incasari_xml import parse_incasari_xml
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
        "passwords into chat). Call saga_login first. After login, saga_context shows firm, "
        "working interval, and closed-period status. saga_list_screens lists onboarded grids; "
        "saga_describe_screen(screen) dumps catalog columns/aliases/lookups (clienti, iesiri_valuta, …). "
        "Generic reads: saga_list_rows / saga_get_row / saga_lookup / saga_export_grid on onboarded screens. "
        "Master data: saga_*_supplier (Furnizori, not Clienti), saga_*_item (Articole), "
        "saga_chart_of_accounts (read). "
        "Named document writes: saga_add_iesire (RON sales; FX routes to saga_add_iesiri_valuta), "
        "saga_add_intrare (purchases; FX uses IntrariValuta; bulk NIR still saga_import_xml), "
        "saga_post_bank_entries (BankBundle or I_/P_ XML via Import extrase; FX Moneda uses Jurnal de bancă valută), "
        "saga_add_casa_entry (Registru de casă; FX Valuta uses Registru de casă valută + GetLastValuta). "
        "saga_validate_document locks/unlocks a journal row (ExecutaValidare / Devalidare); create does not lock. "
        "Reports: saga_run_report(name, filters) — name=period_pack runs balanță + jurnale; "
        "files save under ~/.markus/data/saga/reports/ only when magic bytes are PDF/XLS. "
        "Stock/commercial grids (imobilizari, transferuri, bonuri, productie, inventariere, …) "
        "are readable via saga_list_rows; there is no generic write. "
        "e-Factura: saga_efactura_list / saga_efactura_download are read-only. "
        "saga_efactura_submit / saga_efactura_cancel / saga_close_month / saga_submit_declaration "
        "are human-gated (confirm_write + confirm_phrase); never call them unattended. "
        "saga_generate_declaration may download a local D406/D205/Intrastat PDF. "
        "saga_set_interval changes the toolbar period after confirm_write. saga_about is Despre. "
        "Writes go through named tools only — there is no generic create-row tool. "
        "Optional ingest: saga_parse_facturi_xml / saga_parse_incasari_xml return canonical "
        "documents without writing. Prefer the 3-month browser trust: "
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
        "(create/update/remove/add_iesiri_valuta/add_iesire/add_intrare/post_bank_entries/add_casa_entry/"
        "import_xml/import_iesiri_xml/import_incasari_xml/wipe_data/create_supplier/update_supplier/"
        "remove_supplier/create_item/update_item/remove_item/set_interval/close_month/"
        "efactura_submit/efactura_cancel/validate_document/submit_declaration) require confirm_write=false preview first, then "
        "confirm_write=true after explicit user OK. close_month also needs confirm_phrase='INCHIDE LUNA'; "
        "efactura_submit needs 'TRIMITE EFACTURA'; efactura_cancel needs 'ANULEAZA EFACTURA'; "
        "saga_submit_declaration needs 'TRIMITE DECLARATIE'. "
        "Invoice writes resolve Clienți/Furnizori on confirm and abort if missing (do not auto-create). "
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
    title="SAGA context",
    description=(
        "Read the connected SAGA firm, user, working interval, rights probe, and "
        "closed-period status from Home/LoadOperationalData."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_context() -> dict[str, Any]:
    return saga_context_mod.get_context()


@mcp.tool(
    title="SAGA about",
    description="Read SAGA WEB Despre / version and firm identity from LoadOperationalData.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_about() -> dict[str, Any]:
    return saga_context_mod.about()


@mcp.tool(
    title="SAGA set working interval",
    description=(
        "Change the SAGA toolbar working interval. Preview with confirm_write=false, "
        "then true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_set_interval(
    interval_start: str,
    interval_end: str,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_context_mod.set_interval(interval_start, interval_end, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA close month",
    description=(
        "HUMAN-GATED month close. Preview first. Execute only after explicit user OK with "
        "confirm_write=true and confirm_phrase='INCHIDE LUNA'. Never call unattended."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_close_month(confirm_write: bool = False, confirm_phrase: str = "") -> dict[str, Any]:
    return saga_context_mod.close_month(confirm_write=confirm_write, confirm_phrase=confirm_phrase)


@mcp.tool(
    title="SAGA generate declaration",
    description=(
        "Download a local D406/D205/Intrastat PDF when this WEB build exposes a generator. "
        "Empty name lists declarations. Does not submit to ANAF — use saga_submit_declaration."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_generate_declaration(
    name: str = "",
    filters: dict[str, Any] | None = None,
    format: str = "pdf",
) -> dict[str, Any]:
    return saga_declarations.generate_declaration(name, filters=filters, format=format)


@mcp.tool(
    title="SAGA submit declaration",
    description=(
        "HUMAN-GATED ANAF/SPV submit for D406/D205/Intrastat/e-Transport/REVISAL. "
        "Preview first. Execute only after explicit user OK with confirm_write=true and "
        "confirm_phrase='TRIMITE DECLARATIE'. Never call unattended."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_submit_declaration(
    name: str,
    confirm_write: bool = False,
    confirm_phrase: str = "",
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return saga_declarations.submit_declaration(
        name, confirm_write=confirm_write, confirm_phrase=confirm_phrase, filters=filters
    )


@mcp.tool(
    title="SAGA e-Factura list",
    description=(
        "List e-Factura rows (issued/received as exposed by this WEB build). Read-only. "
        "Does not submit or import. Inbound import may still be desktop-only."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_efactura_list(query: str | None = None, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    return saga_efactura.list_invoices(query=query, page=page, page_size=page_size)


@mcp.tool(
    title="SAGA e-Factura download",
    description="Download one e-Factura XML/PDF by Id / Index / NrDoc. Does not submit to ANAF.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_efactura_download(invoice_id: str) -> dict[str, Any]:
    return saga_efactura.download_invoice(invoice_id)


@mcp.tool(
    title="SAGA e-Factura token status",
    description="Check whether an SPV token is present. Does not return the token or save it.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_efactura_token_status() -> dict[str, Any]:
    return saga_efactura.token_status()


@mcp.tool(
    title="SAGA e-Factura submit",
    description=(
        "HUMAN-GATED ANAF/SPV submit. Preview first. Execute only after explicit user OK with "
        "confirm_write=true and confirm_phrase='TRIMITE EFACTURA'. Never call unattended."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_efactura_submit(
    invoice_id: str, confirm_write: bool = False, confirm_phrase: str = ""
) -> dict[str, Any]:
    return saga_efactura.submit_invoice(
        invoice_id, confirm_write=confirm_write, confirm_phrase=confirm_phrase
    )


@mcp.tool(
    title="SAGA e-Factura cancel",
    description=(
        "HUMAN-GATED ANAF/SPV cancel. Preview first. Execute only after explicit user OK with "
        "confirm_write=true and confirm_phrase='ANULEAZA EFACTURA'. Never call unattended."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_efactura_cancel(
    invoice_id: str, confirm_write: bool = False, confirm_phrase: str = ""
) -> dict[str, Any]:
    return saga_efactura.cancel_invoice(
        invoice_id, confirm_write=confirm_write, confirm_phrase=confirm_phrase
    )


@mcp.tool(
    title="SAGA list screens",
    description=(
        "List onboarded SAGA grids in the schema catalog (operation id, route, named tools). "
        "Writes still use named tools — there is no generic create-row MCP tool."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_list_screens() -> dict[str, Any]:
    return saga_registry.list_screens()


@mcp.tool(
    title="SAGA describe screen",
    description=(
        "Dump the committed schema catalog for a SAGA screen (columns, aliases, required). "
        "Pass an operation id such as clienti, iesiri_valuta, iesiri, jurnal_banca."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_describe_screen(screen: str) -> dict[str, Any]:
    return saga_schema.describe_screen(screen)


@mcp.tool(
    title="SAGA list rows",
    description=(
        "List rows on an onboarded SAGA grid (clienti, furnizori, iesiri, iesiri_valuta, "
        "intrari, jurnal_banca, …). Optional query, paging, and master_id for detail grids."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_list_rows(
    screen: str,
    page: int = 1,
    page_size: int = 50,
    query: str | None = None,
    master_id: str | None = None,
) -> dict[str, Any]:
    return saga_reads.list_rows(
        screen,
        page=page,
        page_size=page_size,
        query=query,
        master_id=master_id,
    )


@mcp.tool(
    title="SAGA get row",
    description=(
        "Fetch one row by primary key / code / document number on an onboarded SAGA grid. "
        "Includes detail lines when the screen has a detail table."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_get_row(screen: str, pk: str, with_details: bool = True) -> dict[str, Any]:
    return saga_reads.get_row(screen, pk, with_details=with_details)


@mcp.tool(
    title="SAGA lookup",
    description=(
        "Combo lookup for a catalog field or selectModel (Tara, Client, Cont, Valuta, …). "
        "Tries the screen controller then Home (Home first for Conturi/Proiecte/Tari/…)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_lookup(screen: str, field: str, query: str = "", limit: int = 50) -> dict[str, Any]:
    return saga_lookups.lookup(screen, field, query=query, limit=limit)


@mcp.tool(
    title="SAGA export grid",
    description=(
        "Export an onboarded SAGA grid via Home/ExportDate. Saves a real xlsx/xls under "
        "~/.markus/data/saga/exports/. HTML error pages are not saved as Excel."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_export_grid(screen: str, query: str | None = None, tip: str = "xlsx") -> dict[str, Any]:
    return saga_exports.export_grid(screen, query=query, tip=tip)


@mcp.tool(
    title="SAGA run report",
    description=(
        "Download a SAGA Situatii report (PDF/XLS). Pass name=balanta|jurnal_cumparari|"
        "jurnal_vanzari|fise_conturi|period_pack|… and optional filters (from/to dates, Cont). "
        "Dates default to the working interval from saga_context. Empty name lists reports. "
        "Saves under ~/.markus/data/saga/reports/ only when magic bytes are PDF/XLS. "
        "Bilanț is local PDF only — do not ANAF-submit from this tool."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_run_report(
    name: str = "",
    filters: dict[str, Any] | None = None,
    format: str = "pdf",
    accounts: str | None = None,
) -> dict[str, Any]:
    return saga_reports.run_report(name, filters=filters, format=format, accounts=accounts)


@mcp.tool(
    title="SAGA parse Facturi XML",
    description=(
        "Parse a SAGA Facturi XML into canonical sales documents (header + lines mapped "
        "through the schema catalog). Does not write to SAGA."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_parse_facturi_xml(xml_path: str) -> dict[str, Any]:
    from pathlib import Path
    from xml.etree import ElementTree as ET

    source = Path(str(xml_path or "")).expanduser()
    if not str(xml_path or "").strip():
        return {"ok": False, "error": "xml_path is required."}
    if not source.is_file():
        return {"ok": False, "error": f"XML file not found: {source}"}
    try:
        parsed = parse_facturi_xml(source)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"Invalid XML: {exc}", "path": str(source)}
    return {"ok": True, **parsed}


@mcp.tool(
    title="SAGA parse încasări XML",
    description=(
        "Parse a SAGA Încasări or Plăți XML into a canonical bank bundle mapped through "
        "the schema catalog. Does not write to SAGA."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_parse_incasari_xml(xml_path: str) -> dict[str, Any]:
    from pathlib import Path
    from xml.etree import ElementTree as ET

    source = Path(str(xml_path or "")).expanduser()
    if not str(xml_path or "").strip():
        return {"ok": False, "error": "xml_path is required."}
    if not source.is_file():
        return {"ok": False, "error": f"XML file not found: {source}"}
    try:
        parsed = parse_incasari_xml(source)
    except ET.ParseError as exc:
        return {"ok": False, "error": f"Invalid XML: {exc}", "path": str(source)}
    return {"ok": True, **parsed}


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
    title="SAGA list suppliers",
    description="List SAGA Furnizori (suppliers). Not Clienți — use saga_list_partners for clients.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_list_suppliers(page: int = 1, page_size: int = 50, query: str | None = None) -> dict[str, Any]:
    return saga_nomenclator.list_records("furnizori", noun="supplier", page=page, page_size=page_size, query=query)


@mcp.tool(
    title="SAGA search suppliers",
    description="Search SAGA Furnizori by name, code, or CUI.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_search_suppliers(query: str, limit: int = 50) -> dict[str, Any]:
    return saga_nomenclator.list_records("furnizori", noun="supplier", page=1, page_size=limit, query=query)


@mcp.tool(
    title="SAGA get supplier",
    description="Fetch one SAGA Furnizor by exact id/cod/CUI/name.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_get_supplier(supplier_id: str) -> dict[str, Any]:
    return saga_nomenclator.get_record("furnizori", supplier_id, noun="supplier")


@mcp.tool(
    title="SAGA supplier fields",
    description="List writable Furnizori fields/aliases. Pass only user-specified fields on create/update.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_supplier_fields() -> dict[str, Any]:
    return saga_nomenclator.field_catalog("furnizori")


@mcp.tool(
    title="SAGA create supplier",
    description="Create a Furnizor. Preview with confirm_write=false, then true after explicit user OK.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_create_supplier(fields: dict[str, Any], confirm_write: bool = False) -> dict[str, Any]:
    return saga_nomenclator.create_record(
        "furnizori", fields, noun="supplier", confirm_write=confirm_write, action="create_supplier"
    )


@mcp.tool(
    title="SAGA update supplier",
    description="Update only user-specified Furnizori fields. Preview then confirm_write=true.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_update_supplier(
    supplier_id: str, fields: dict[str, Any], confirm_write: bool = False
) -> dict[str, Any]:
    return saga_nomenclator.update_record(
        "furnizori",
        supplier_id,
        fields,
        noun="supplier",
        confirm_write=confirm_write,
        action="update_supplier",
    )


@mcp.tool(
    title="SAGA remove supplier",
    description="Remove a Furnizor by exact id. Preview then confirm_write=true.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_remove_supplier(supplier_id: str, confirm_write: bool = False) -> dict[str, Any]:
    return saga_nomenclator.remove_record(
        "furnizori", supplier_id, noun="supplier", confirm_write=confirm_write, action="remove_supplier"
    )


@mcp.tool(
    title="SAGA list items",
    description="List SAGA Articole (articles/services).",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_list_items(page: int = 1, page_size: int = 50, query: str | None = None) -> dict[str, Any]:
    return saga_nomenclator.list_records("articole", noun="item", page=page, page_size=page_size, query=query)


@mcp.tool(
    title="SAGA get item",
    description="Fetch one Articol by code or name.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_get_item(item_id: str) -> dict[str, Any]:
    return saga_nomenclator.get_record("articole", item_id, noun="item")


@mcp.tool(
    title="SAGA item fields",
    description="List writable Articole fields/aliases. Do not invent TVA, pret, or SGR.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def saga_item_fields() -> dict[str, Any]:
    return saga_nomenclator.field_catalog("articole")


@mcp.tool(
    title="SAGA create item",
    description="Create an Articol. Preview with confirm_write=false, then true after explicit user OK.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_create_item(fields: dict[str, Any], confirm_write: bool = False) -> dict[str, Any]:
    return saga_nomenclator.create_record(
        "articole", fields, noun="item", confirm_write=confirm_write, action="create_item"
    )


@mcp.tool(
    title="SAGA update item",
    description="Update only user-specified Articole fields. Preview then confirm_write=true.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_update_item(item_id: str, fields: dict[str, Any], confirm_write: bool = False) -> dict[str, Any]:
    return saga_nomenclator.update_record(
        "articole", item_id, fields, noun="item", confirm_write=confirm_write, action="update_item"
    )


@mcp.tool(
    title="SAGA remove item",
    description="Remove an Articol by exact code. Preview then confirm_write=true.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
)
def saga_remove_item(item_id: str, confirm_write: bool = False) -> dict[str, Any]:
    return saga_nomenclator.remove_record(
        "articole", item_id, noun="item", confirm_write=confirm_write, action="remove_item"
    )


@mcp.tool(
    title="SAGA chart of accounts",
    description="List Plan de conturi (read-only). Optional query filter.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
def saga_chart_of_accounts(page: int = 1, page_size: int = 100, query: str | None = None) -> dict[str, Any]:
    result = saga_nomenclator.list_records(
        "plan_conturi", noun="account", page=page, page_size=page_size, query=query
    )
    if result.get("ok"):
        result["accounts"] = result.get("rows") or result.get("accounts") or []
    return result


@mcp.tool(
    title="SAGA add Ieșire",
    description=(
        "Create a RON sales invoice (Ieșiri) from header + lines (chat/PDF/XML mapped fields). "
        "If Valuta is not RON, routes to saga_add_iesiri_valuta. Each line needs Cont. "
        "Preview with confirm_write=false, then true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_add_iesire(
    header: dict[str, Any] | None = None,
    lines: list[dict[str, Any]] | None = None,
    document: dict[str, Any] | None = None,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_invoices.add_iesire(header, lines, document, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA add Intrare",
    description=(
        "Create a purchase invoice (Intrări). Required: Furnizor or Cod, Data, lines with Cont. "
        "Non-RON Valuta uses Intrări valută (Curs auto-filled). Bulk NIR still uses saga_import_xml. "
        "Preview with confirm_write=false, then true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_add_intrare(
    header: dict[str, Any] | None = None,
    lines: list[dict[str, Any]] | None = None,
    document: dict[str, Any] | None = None,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_invoices.add_intrare(header, lines, document, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA post bank entries",
    description=(
        "Post a bank bundle (încasări/plăți) on Jurnal de Bancă via Import extrase + Asociere. "
        "Pass a parsed document or entries[]. Chat entries are emitted to I_/P_ XML then uploaded. "
        "Non-RON Moneda uses the same Import extrase workflow on Jurnal de bancă valută. "
        "Preview with confirm_write=false, then true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_post_bank_entries(
    document: dict[str, Any] | None = None,
    entries: list[dict[str, Any]] | None = None,
    kind: str = "bank_receipts",
    account: str = "",
    partner: str = "",
    asociere: bool = True,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_bank.post_bank_entries(
        document,
        entries=entries,
        kind=kind,
        account=account,
        partner=partner,
        asociere=asociere,
        confirm_write=confirm_write,
    )


@mcp.tool(
    title="SAGA add casă entry",
    description=(
        "Add a Registru de casă entry. Required: Cont, Suma; also pass Data. "
        "Non-RON Valuta/Moneda posts on Registru de casă valută (Curs from GetLastValuta). "
        "Preview with confirm_write=false, then true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_add_casa_entry(fields: dict[str, Any], confirm_write: bool = False) -> dict[str, Any]:
    return saga_bank.add_casa_entry(fields, confirm_write=confirm_write)


@mcp.tool(
    title="SAGA validate document",
    description=(
        "Lock (ExecutaValidare) or unlock (Devalidare) a journal document. Creating a row "
        "does not lock it. Pass screen=iesiri|intrari|iesiri_valuta|… and pk. "
        "Preview with confirm_write=false, then true after explicit user OK."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
def saga_validate_document(
    screen: str,
    pk: str,
    devalidate: bool = False,
    confirm_write: bool = False,
) -> dict[str, Any]:
    return saga_validate_doc.validate_document(
        screen, pk, devalidate=devalidate, confirm_write=confirm_write
    )


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

