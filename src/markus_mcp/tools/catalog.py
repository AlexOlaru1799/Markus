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
        name="saga_context",
        title="SAGA context",
        description="Read connected firm, working interval, rights, and closed-period status.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_about",
        title="SAGA about",
        description="Read SAGA WEB Despre / version and firm identity.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_set_interval",
        title="SAGA set working interval",
        description="Change the SAGA toolbar working interval; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_close_month",
        title="SAGA close month",
        description="HUMAN-GATED month close; requires confirm_write and confirm_phrase INCHIDE LUNA.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_generate_declaration",
        title="SAGA generate declaration",
        description="Download a local D406/D205/Intrastat PDF when available; does not submit to ANAF.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_submit_declaration",
        title="SAGA submit declaration",
        description="HUMAN-GATED ANAF submit for D406/D205/Intrastat/e-Transport/REVISAL; confirm_phrase TRIMITE DECLARATIE.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_efactura_list",
        title="SAGA e-Factura list",
        description="List e-Factura rows (read-only; does not submit).",
        read_only=True,
    ),
    ToolInfo(
        name="saga_efactura_download",
        title="SAGA e-Factura download",
        description="Download one e-Factura XML/PDF; does not submit to ANAF.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_efactura_token_status",
        title="SAGA e-Factura token status",
        description="Check whether an SPV token is present (does not return the token).",
        read_only=True,
    ),
    ToolInfo(
        name="saga_efactura_submit",
        title="SAGA e-Factura submit",
        description="HUMAN-GATED ANAF submit; requires confirm_write and confirm_phrase TRIMITE EFACTURA.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_efactura_cancel",
        title="SAGA e-Factura cancel",
        description="HUMAN-GATED ANAF cancel; requires confirm_write and confirm_phrase ANULEAZA EFACTURA.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_list_screens",
        title="SAGA list screens",
        description="List onboarded SAGA grids in the schema catalog.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_describe_screen",
        title="SAGA describe screen",
        description="Dump catalog columns/aliases/lookups for an onboarded SAGA screen.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_list_rows",
        title="SAGA list rows",
        description="List rows on an onboarded SAGA grid with optional filter and paging.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_get_row",
        title="SAGA get row",
        description="Fetch one SAGA grid row by pk/code/document number; includes details when present.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_lookup",
        title="SAGA lookup",
        description="Combo lookup via GetData_ComboBox_<selectModel> with Home redirects.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_export_grid",
        title="SAGA export grid",
        description="Export an onboarded grid via Home/ExportDate to a real xlsx/xls file.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_run_report",
        title="SAGA run report",
        description=(
            "Download a Situatii report (or period_pack) as PDF/XLS; refuses HTML error pages."
        ),
        read_only=True,
    ),
    ToolInfo(
        name="saga_parse_facturi_xml",
        title="SAGA parse Facturi XML",
        description="Parse a Facturi XML into canonical sales documents; does not write.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_parse_incasari_xml",
        title="SAGA parse încasări XML",
        description="Parse an I_/P_ XML into a canonical bank bundle; does not write.",
        read_only=True,
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
        name="saga_list_suppliers",
        title="SAGA list suppliers",
        description="List SAGA Furnizori (not Clienți).",
        read_only=True,
    ),
    ToolInfo(
        name="saga_search_suppliers",
        title="SAGA search suppliers",
        description="Search SAGA Furnizori by name, code, or CUI.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_get_supplier",
        title="SAGA get supplier",
        description="Fetch one Furnizor by exact id/cod/CUI/name.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_supplier_fields",
        title="SAGA supplier fields",
        description="List writable Furnizori fields/aliases.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_create_supplier",
        title="SAGA create supplier",
        description="Create a Furnizor with only user-specified fields; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_update_supplier",
        title="SAGA update supplier",
        description="Update only user-specified Furnizori fields; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_remove_supplier",
        title="SAGA remove supplier",
        description="Remove a Furnizor by exact id; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_list_items",
        title="SAGA list items",
        description="List SAGA Articole.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_get_item",
        title="SAGA get item",
        description="Fetch one Articol by code or name.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_item_fields",
        title="SAGA item fields",
        description="List writable Articole fields/aliases.",
        read_only=True,
    ),
    ToolInfo(
        name="saga_create_item",
        title="SAGA create item",
        description="Create an Articol with only user-specified fields; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_update_item",
        title="SAGA update item",
        description="Update only user-specified Articole fields; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_remove_item",
        title="SAGA remove item",
        description="Remove an Articol by exact code; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_chart_of_accounts",
        title="SAGA chart of accounts",
        description="List Plan de conturi (read-only).",
        read_only=True,
    ),
    ToolInfo(
        name="saga_add_iesire",
        title="SAGA add Ieșire",
        description="Create a RON sales invoice (header + lines); FX routes to IesiriValuta; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_add_intrare",
        title="SAGA add Intrare",
        description="Create a purchase invoice (header + lines); FX uses Intrări valută; requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_post_bank_entries",
        title="SAGA post bank entries",
        description="Post a BankBundle or I_/P_ XML via Jurnal de Bancă Import extrase (FX Moneda uses valută journal); requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_add_casa_entry",
        title="SAGA add casă entry",
        description="Add a Registru de casă entry (FX Valuta routes to casă valută); requires confirm_write.",
        read_only=False,
    ),
    ToolInfo(
        name="saga_validate_document",
        title="SAGA validate document",
        description="Lock or unlock a journal document via ExecutaValidare / Devalidare; requires confirm_write.",
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
    ToolInfo(
        name="saga_import_xml",
        title="SAGA import XML",
        description=(
            "Upload a Facturi XML on SAGA Import date and import it; requires confirm_write."
        ),
        read_only=False,
    ),
    ToolInfo(
        name="saga_import_iesiri_xml",
        title="SAGA import Ieșiri XML",
        description=(
            "Create RON Ieșiri from a Facturi XML (keeps NrDoc); skips existing numbers; "
            "requires confirm_write."
        ),
        read_only=False,
    ),
    ToolInfo(
        name="saga_import_incasari_xml",
        title="SAGA import încasări XML",
        description=(
            "Upload an I_/P_ XML on Jurnal de Bancă Import extrase, fill client/supplier, "
            "associate via SAGA DisplayData(codFactura), then Accept; requires confirm_write."
        ),
        read_only=False,
    ),
    ToolInfo(
        name="saga_wipe_data",
        title="SAGA wipe data",
        description=(
            "Delete Jurnal de bancă (incl. Import extrase staging), Intrări/Ieșiri "
            "(cu/fără valută, lines and allocations first), then Furnizori/Clienți; "
            "requires confirm_write."
        ),
        read_only=False,
    ),
    ToolInfo(
        name="smartbill_status",
        title="SmartBill status",
        description=(
            "Check whether the SmartBill API token is stored and probe the public API "
            "when email and CIF are present."
        ),
        read_only=True,
    ),
    ToolInfo(
        name="smartbill_list_supplier_invoices",
        title="SmartBill list supplier invoices",
        description="List Documente furnizori for a date range or this_month/last_month.",
        read_only=True,
    ),
    ToolInfo(
        name="smartbill_export_supplier_invoices_xls",
        title="SmartBill export supplier invoices Excel",
        description="Export Documente furnizori to Excel under ~/.markus/data/smartbill/.",
        read_only=True,
    ),
    ToolInfo(
        name="smartbill_invoices_to_saga_xml",
        title="SmartBill invoices to SAGA XML",
        description=(
            "Convert Documente furnizori XLS to SAGA Facturi XML (NIR required, skip RO CIF)."
        ),
        read_only=True,
    ),
)


def tool_catalog_as_dicts() -> list[dict[str, object]]:
    return [asdict(tool) for tool in TOOL_CATALOG]
