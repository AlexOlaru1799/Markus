"""Registry of onboarded SAGA screens (operation id → ScreenSpec)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Risk = Literal["low", "medium", "high"]
WriteStyle = Literal["classic", "ex"]


@dataclass(frozen=True)
class ScreenSpec:
    operation: str
    title: str
    route: str
    table: str
    pk: str
    schema_id: str
    write_style: WriteStyle
    risk: Risk
    detail_operation: str | None = None
    named_tools: tuple[str, ...] = ()
    employee_writes: bool = False
    usage: str = ""
    notes: tuple[str, ...] = ()
    get_data: tuple[str, ...] = ()
    create: tuple[str, ...] = ()
    edit: tuple[str, ...] = ()
    delete: tuple[str, ...] = ()
    next_index: tuple[str, ...] = ()


SCREENS: dict[str, ScreenSpec] = {
    "clienti": ScreenSpec(
        operation="clienti",
        title="Clienți",
        route="Clienti",
        table="Clienti",
        pk="Cod",
        schema_id="clienti",
        write_style="ex",
        risk="low",
        named_tools=(
            "saga_list_partners",
            "saga_search_partners",
            "saga_get_partner",
            "saga_partner_fields",
            "saga_create_partner",
            "saga_update_partner",
            "saga_remove_partner",
        ),
        employee_writes=True,
        usage="Pass only user-specified Clienti fields. Denumire is required on create.",
        get_data=("Clienti/GetData_Clienti",),
        create=("Clienti/Create_Clienti",),
        edit=("Clienti/Edit_Clienti",),
        delete=("Clienti/Delete_Clienti",),
    ),
    "furnizori": ScreenSpec(
        operation="furnizori",
        title="Furnizori",
        route="Furnizori",
        table="Furnizori",
        pk="Cod",
        schema_id="furnizori",
        write_style="ex",
        risk="low",
        named_tools=(
            "saga_list_suppliers",
            "saga_search_suppliers",
            "saga_get_supplier",
            "saga_supplier_fields",
            "saga_create_supplier",
            "saga_update_supplier",
            "saga_remove_supplier",
        ),
        employee_writes=True,
        usage="Pass only user-specified Furnizori fields. Denumire is required on create.",
        get_data=("Furnizori/GetData_Furnizori",),
        create=("Furnizori/Create_Furnizori",),
        edit=("Furnizori/Edit_Furnizori",),
        delete=("Furnizori/Delete_Furnizori",),
        next_index=("Furnizori/GetNextIndex",),
    ),
    "articole": ScreenSpec(
        operation="articole",
        title="Articole",
        route="Articole",
        table="Articole",
        pk="Cod",
        schema_id="articole",
        write_style="ex",
        risk="low",
        named_tools=(
            "saga_list_items",
            "saga_get_item",
            "saga_item_fields",
            "saga_create_item",
            "saga_update_item",
            "saga_remove_item",
        ),
        employee_writes=True,
        usage="Pass only user-specified Articole fields. Denumire is required on create.",
        get_data=("Articole/GetData_Articole",),
        create=("Articole/Create_Articole",),
        edit=("Articole/Edit_Articole",),
        delete=("Articole/Delete_Articole",),
        next_index=("Articole/GetNextIndex",),
    ),
    "plan_conturi": ScreenSpec(
        operation="plan_conturi",
        title="Plan de conturi",
        route="PlanConturi",
        table="PlanConturi",
        pk="Cont",
        schema_id="plan_conturi",
        write_style="classic",
        risk="high",
        named_tools=(
            "saga_chart_of_accounts",
            "saga_account_fields",
            "saga_create_account",
        ),
        employee_writes=True,
        usage="Pass only user-specified Plan de conturi fields. Cont, Denumire, and Tip A/P/B are required on create.",
        get_data=("PlanConturi/GetData_PlanConturi", "PlanConturi/GetData"),
        create=("PlanConturi/Create_PlanConturi",),
        edit=("PlanConturi/Edit_PlanConturi",),
        delete=("PlanConturi/Delete_PlanConturi",),
    ),
    "gestiuni": ScreenSpec(
        operation="gestiuni",
        title="Gestiuni",
        route="Gestiuni",
        table="Gestiuni",
        pk="Cod",
        schema_id="gestiuni",
        write_style="ex",
        risk="low",
        employee_writes=False,
        get_data=("Gestiuni/GetData_Gestiuni",),
        next_index=("Gestiuni/GetNextPK",),
    ),
    "tipuri_articole": ScreenSpec(
        operation="tipuri_articole",
        title="Tipuri de articole / servicii",
        route="TipArticole",
        table="TipArticole",
        pk="Cod",
        schema_id="tipuri_articole",
        write_style="ex",
        risk="low",
        employee_writes=False,
        get_data=("TipArticole/GetData_TipArticole", "TipArticole/GetData"),
    ),
    "iesiri_valuta": ScreenSpec(
        operation="iesiri_valuta",
        title="Ieșiri valută",
        route="IesiriValuta",
        table="IesiriValuta",
        pk="ID_Iesire",
        schema_id="iesiri_valuta",
        write_style="classic",
        risk="medium",
        detail_operation="iesiri_valuta_detalii",
        named_tools=("saga_iesiri_valuta_fields", "saga_add_iesiri_valuta"),
        employee_writes=True,
        usage="Required: Client or Cod, Valuta, Data. Optional: Scadent, NrDoc, Tip, Curs, Agent, notes.",
        notes=(
            "Tip '' = Factura (default).",
            "Cont is mandatory on each line.",
            "Curs is auto-fetched from IntrariValuta/GetCursValutar when omitted.",
        ),
        get_data=("IesiriValuta/GetData_IesiriValuta", "IesiriValuta/GetData"),
        create=("IesiriValuta/Create_IesiriValuta",),
        delete=("IesiriValuta/Delete_IesiriValuta",),
        next_index=("IesiriValuta/GetNrIesiriValutaTip",),
    ),
    "iesiri_valuta_detalii": ScreenSpec(
        operation="iesiri_valuta_detalii",
        title="Ieșiri valută — linii",
        route="IesiriValuta",
        table="IesiriValutaDetalii",
        pk="ID_IesireDet",
        schema_id="iesiri_valuta_detalii",
        write_style="classic",
        risk="medium",
        named_tools=("saga_add_iesiri_valuta",),
        employee_writes=True,
        usage=(
            "Required per line: Cont, and amounts (Cantitate + PretUnitarValuta, or explicit totals). "
            "Also useful: Denumire, Cod_Art/Cod, UM, TVA_ART, Gestiune."
        ),
        get_data=(
            "IesiriValuta/GetData_IesiriValutaDetalii",
            "IesiriValutaDetalii/GetData_IesiriValutaDetalii",
        ),
        create=(
            "IesiriValuta/Create_IesiriValutaDetalii",
            "IesiriValutaDetalii/Create_IesiriValutaDetalii",
        ),
        delete=(
            "IesiriValuta/Delete_IesiriValutaDetalii",
            "IesiriValutaDetalii/Delete_IesiriValutaDetalii",
        ),
    ),
    "iesiri": ScreenSpec(
        operation="iesiri",
        title="Ieșiri",
        route="Iesiri",
        table="Iesiri",
        pk="ID_Iesire",
        schema_id="iesiri",
        write_style="classic",
        risk="medium",
        detail_operation="iesiri_detalii",
        named_tools=("saga_import_iesiri_xml", "saga_add_iesire"),
        employee_writes=True,
        usage="RON sales invoices. Required: Client or Cod, Data. saga_add_iesire is the format-agnostic write.",
        get_data=("Iesiri/GetData_Iesiri",),
        create=("Iesiri/Create_Iesiri",),
        delete=("Iesiri/Delete_Iesiri",),
        next_index=("Iesiri/GetNrDoc", "Iesiri/GetNextIndex"),
    ),
    "iesiri_detalii": ScreenSpec(
        operation="iesiri_detalii",
        title="Ieșiri — linii",
        route="Iesiri",
        table="IesiriDetalii",
        pk="ID_IesireDet",
        schema_id="iesiri_detalii",
        write_style="classic",
        risk="medium",
        named_tools=("saga_import_iesiri_xml", "saga_add_iesire"),
        employee_writes=True,
        get_data=("Iesiri/GetData_IesiriDetalii", "IesiriDetalii/GetData_IesiriDetalii"),
        create=("Iesiri/Create_IesiriDetalii", "IesiriDetalii/Create_IesiriDetalii"),
        delete=("Iesiri/Delete_IesiriDetalii", "IesiriDetalii/Delete_IesiriDetalii"),
    ),
    "intrari": ScreenSpec(
        operation="intrari",
        title="Intrări",
        route="Intrari",
        table="Intrari",
        pk="ID_Intrare",
        schema_id="intrari",
        write_style="classic",
        risk="medium",
        detail_operation="intrari_detalii",
        named_tools=("saga_add_intrare",),
        employee_writes=True,
        usage="RON purchase invoices. Required: Furnizor or Cod, Data. Bulk NIR stays Import date.",
        get_data=("Intrari/GetData_Intrari",),
        create=("Intrari/Create_Intrari",),
        delete=("Intrari/Delete_Intrari",),
        next_index=("Intrari/GetNrDoc", "Intrari/GetNextIndex"),
    ),
    "intrari_detalii": ScreenSpec(
        operation="intrari_detalii",
        title="Intrări — linii",
        route="Intrari",
        table="IntrariDetalii",
        pk="ID_IntrareDet",
        schema_id="intrari_detalii",
        write_style="classic",
        risk="medium",
        named_tools=("saga_add_intrare",),
        employee_writes=True,
        get_data=("Intrari/GetData_IntrariDetalii", "IntrariDetalii/GetData_IntrariDetalii"),
        create=("Intrari/Create_IntrariDetalii", "IntrariDetalii/Create_IntrariDetalii"),
        delete=("Intrari/Delete_IntrariDetalii", "IntrariDetalii/Delete_IntrariDetalii"),
    ),
    "intrari_valuta": ScreenSpec(
        operation="intrari_valuta",
        title="Intrări valută",
        route="IntrariValuta",
        table="IntrariValuta",
        pk="ID_Intrare",
        schema_id="intrari_valuta",
        write_style="classic",
        risk="medium",
        detail_operation="intrari_valuta_detalii",
        named_tools=("saga_add_intrare",),
        employee_writes=True,
        usage="FX purchases. Curs auto-filled from GetCursValutar when omitted.",
        get_data=("IntrariValuta/GetData_IntrariValuta",),
        create=("IntrariValuta/Create_IntrariValuta",),
        delete=("IntrariValuta/Delete_IntrariValuta",),
        next_index=("IntrariValuta/GetNrDoc", "IntrariValuta/GetNrIntrariValutaTip"),
    ),
    "intrari_valuta_detalii": ScreenSpec(
        operation="intrari_valuta_detalii",
        title="Intrări valută — linii",
        route="IntrariValuta",
        table="IntrariValutaDetalii",
        pk="ID_IntrareDet",
        schema_id="intrari_valuta_detalii",
        write_style="classic",
        risk="medium",
        named_tools=("saga_add_intrare",),
        employee_writes=True,
        get_data=(
            "IntrariValuta/GetData_IntrariValutaDetalii",
            "IntrariValutaDetalii/GetData_IntrariValutaDetalii",
        ),
        create=(
            "IntrariValuta/Create_IntrariValutaDetalii",
            "IntrariValutaDetalii/Create_IntrariValutaDetalii",
        ),
        delete=(
            "IntrariValuta/Delete_IntrariValutaDetalii",
            "IntrariValutaDetalii/Delete_IntrariValutaDetalii",
        ),
    ),
    "jurnal_banca": ScreenSpec(
        operation="jurnal_banca",
        title="Jurnal de bancă",
        route="JurnalDeBanca",
        table="Casa",
        pk="IdNota",
        schema_id="jurnal_banca",
        write_style="classic",
        risk="medium",
        named_tools=("saga_import_incasari_xml", "saga_post_bank_entries"),
        employee_writes=True,
        usage="Bank receipts/payments. Posts via Import extrase + Asociere, not grid.create on Solduri.",
        get_data=("JurnalDeBanca/GetData_Casa",),
        delete=("RegistruCasa/Delete_Casa",),
    ),
    "jurnal_banca_valuta": ScreenSpec(
        operation="jurnal_banca_valuta",
        title="Jurnal de bancă valută",
        route="JurnalDeBancaValuta",
        table="Casa",
        pk="IdNota",
        schema_id="jurnal_banca_valuta",
        write_style="classic",
        risk="medium",
        named_tools=("saga_import_incasari_xml", "saga_post_bank_entries"),
        employee_writes=True,
        usage="FX bank journal. Same Import extrase workflow when Moneda is not RON. Not grid.create on Solduri.",
        get_data=(
            "JurnalDeBancaValuta/GetData_Casa",
            "JurnalDeBanca/GetData_CasaValuta",
            "JurnalDeBanca/GetData_Casa",
        ),
        delete=("RegistruCasa/Delete_Casa",),
    ),
    "registru_casa": ScreenSpec(
        operation="registru_casa",
        title="Registru de casă",
        route="RegistruCasa",
        table="Casa",
        pk="IdNota",
        schema_id="registru_casa",
        write_style="classic",
        risk="medium",
        named_tools=("saga_add_casa_entry",),
        employee_writes=True,
        usage="Cash register entries. Required: Data, Suma, Cont.",
        get_data=("RegistruCasa/GetData_Casa", "JurnalDeBanca/GetData_Casa"),
        create=("RegistruCasa/Create_Casa",),
        delete=("RegistruCasa/Delete_Casa",),
    ),
    "registru_casa_valuta": ScreenSpec(
        operation="registru_casa_valuta",
        title="Registru de casă valută",
        route="RegistruCasaValuta",
        table="Casa",
        pk="IdNota",
        schema_id="registru_casa_valuta",
        write_style="classic",
        risk="medium",
        named_tools=("saga_add_casa_entry",),
        employee_writes=True,
        usage="FX cash register. saga_add_casa_entry routes here when Valuta/Moneda is not RON. Curs from GetLastValuta.",
        get_data=(
            "RegistruCasaValuta/GetData_Casa",
            "RegistruCasa/GetData_CasaValuta",
            "RegistruCasa/GetData_Casa",
        ),
        create=("RegistruCasaValuta/Create_Casa", "RegistruCasa/Create_Casa"),
        delete=("RegistruCasa/Delete_Casa",),
    ),
}


def _read_only(
    operation: str,
    title: str,
    route: str,
    table: str,
    pk: str,
    *,
    write_style: WriteStyle = "ex",
    risk: Risk = "low",
    get_data: tuple[str, ...] = (),
    next_index: tuple[str, ...] = (),
    named_tools: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
    usage: str = "Read-only until a job needs a named write.",
) -> ScreenSpec:
    return ScreenSpec(
        operation=operation,
        title=title,
        route=route,
        table=table,
        pk=pk,
        schema_id=operation,
        write_style=write_style,
        risk=risk,
        named_tools=named_tools,
        employee_writes=False,
        usage=usage,
        notes=notes or ("Best-effort catalog until a live tableModel probe.",),
        get_data=get_data or (f"{route}/GetData_{table}",),
        next_index=next_index,
    )


SCREENS.update(
    {
        "agenti": _read_only("agenti", "Agenți", "Agenti", "Agenti", "Cod"),
        "grupe": _read_only("grupe", "Grupe", "Grupe", "Grupe", "Cod"),
        "filiale": _read_only("filiale", "Filiale", "Filiale", "Filiale", "Cod"),
        "actionari": _read_only("actionari", "Acționari", "Actionari", "Actionari", "Cod"),
        "masini": _read_only("masini", "Mașini", "Masini", "Masini", "Cod"),
        "salariati": _read_only(
            "salariati",
            "Salariați",
            "Salariati",
            "Salariati",
            "Cod",
            risk="high",
            usage="Employees. Read-only. Payroll execute stays human-gated.",
        ),
        "articole_contabile": _read_only(
            "articole_contabile",
            "Articole contabile",
            "Registru",
            "Registru",
            "IdNota",
            write_style="classic",
            risk="medium",
            get_data=("Registru/GetData_Registru", "Registru/GetData_ArticoleContabile"),
        ),
        "imobilizari": _read_only(
            "imobilizari",
            "Imobilizări",
            "Imobilizari",
            "Imobilizari",
            "NrInventar",
            write_style="classic",
            risk="medium",
            next_index=("Imobilizari/GetNrInventar",),
        ),
        "transferuri": _read_only(
            "transferuri",
            "Transferuri",
            "Transferuri",
            "Transferuri",
            "ID_Transfer",
            write_style="classic",
            risk="medium",
            next_index=("Transferuri/GetNrDoc",),
        ),
        "bonuri": _read_only(
            "bonuri",
            "Bonuri de consum",
            "Bonuri",
            "Bonuri",
            "ID_Bon",
            write_style="classic",
            risk="medium",
        ),
        "bonuri_oi": _read_only(
            "bonuri_oi",
            "Dare în folosință ob. inv.",
            "BonuriOI",
            "BonuriOI",
            "ID_Bon",
            write_style="classic",
            risk="medium",
        ),
        "productie": _read_only(
            "productie",
            "Producție",
            "Productie",
            "Productie",
            "ID_Productie",
            write_style="classic",
            risk="medium",
        ),
        "inventariere": _read_only(
            "inventariere",
            "Inventariere",
            "Inventariere",
            "Inventariere",
            "ID_Inventar",
            write_style="classic",
            risk="medium",
        ),
        "dezmembrari": _read_only(
            "dezmembrari",
            "Dezmembrări",
            "Dezmembrari",
            "Dezmembrari",
            "Id",
            write_style="classic",
            risk="high",
            usage="E only; no unattended write.",
        ),
        "operatii_speciale": _read_only(
            "operatii_speciale",
            "Operații speciale",
            "OperatiiSpeciale",
            "OperatiiSpeciale",
            "Id",
            write_style="classic",
            risk="high",
            usage="E only; no unattended write.",
        ),
        "reglari_descarcare": _read_only(
            "reglari_descarcare",
            "Reglări descărcare",
            "ReglariDescarcare",
            "ReglariDescarcare",
            "Id",
            write_style="classic",
            risk="high",
            usage="E only; no unattended write.",
        ),
        "deconturi": _read_only(
            "deconturi",
            "Deconturi",
            "Deconturi",
            "Deconturi",
            "ID_Decont",
            write_style="classic",
            risk="medium",
        ),
        "deconturi_valuta": _read_only(
            "deconturi_valuta",
            "Deconturi valută",
            "DeconturiValuta",
            "DeconturiValuta",
            "ID_Decont",
            write_style="classic",
            risk="medium",
            get_data=("DeconturiValuta/GetData_Deconturi", "Deconturi/GetData_DeconturiValuta"),
            usage="FX settlements. Read-only until a job exists.",
        ),
        "cecuri": _read_only(
            "cecuri",
            "Cecuri / BO",
            "Cecuri",
            "Cecuri",
            "Id",
            write_style="classic",
            risk="medium",
        ),
        "comenzi": _read_only(
            "comenzi",
            "Comenzi",
            "Comenzi",
            "Comenzi",
            "ID_Comanda",
            write_style="classic",
            risk="medium",
        ),
        "contracte": _read_only(
            "contracte",
            "Contracte",
            "Contracte",
            "Contracte",
            "ID_Contract",
            write_style="classic",
            risk="medium",
            next_index=("Contracte/GetNrContracte",),
            usage="Read-only. GenerareFacturi stays confirm_write when a named tool exists.",
        ),
        "diurne": _read_only(
            "diurne",
            "Diurne",
            "Diurne",
            "Diurne",
            "Id",
            write_style="classic",
            risk="medium",
        ),
        "cheltuieli_avans": _read_only(
            "cheltuieli_avans",
            "Cheltuieli / venituri în avans",
            "CheltuieliAvans",
            "CheltuieliAvans",
            "Id",
            write_style="classic",
            risk="medium",
            get_data=(
                "CheltuieliAvans/GetData_CheltuieliAvans",
                "VenituriAvans/GetData_VenituriAvans",
            ),
        ),
        "state_salarii": _read_only(
            "state_salarii",
            "State salarii",
            "StateSalarii",
            "StateSalarii",
            "Id",
            write_style="classic",
            risk="high",
            usage="Payroll sheets. Read-only; D112/filings stay human-gated.",
        ),
        "numere_serii": _read_only(
            "numere_serii",
            "Numere și serii",
            "NumereSiSerii",
            "NumereSiSerii",
            "Cod",
            risk="medium",
            usage="Document series. Adapters call GetNrDoc / GetNrIesiriValutaTip when NrDoc is omitted (auto_filled).",
        ),
        "efactura": _read_only(
            "efactura",
            "e-Facturi",
            "EFactura",
            "EFactura",
            "Id",
            write_style="classic",
            risk="high",
            named_tools=("saga_efactura_list", "saga_efactura_download"),
            get_data=(
                "EFactura/LoadFacturiImport",
                "EFactura/GetData_EFactura",
                "ImportEFactura/GetData_ImportEFactura",
                "ImportEFacturiPrimite/GetData_ImportEFacturiPrimite",
            ),
            usage="List/download e-Factura. Submit/cancel/token stay human-gated.",
        ),
    }
)


def get_screen(operation: str) -> ScreenSpec | None:
    key = (operation or "").strip().casefold()
    if key in SCREENS:
        return SCREENS[key]
    for spec in SCREENS.values():
        if spec.route.casefold() == key:
            return spec
    for spec in SCREENS.values():
        if spec.table.casefold() == key:
            return spec
    return None


def require_screen(operation: str) -> ScreenSpec:
    spec = get_screen(operation)
    if spec is None:
        known = ", ".join(sorted(SCREENS))
        raise KeyError(f"Unknown SAGA screen '{operation}'. Known: {known}")
    return spec


def list_operation_ids() -> list[str]:
    return sorted(SCREENS)


def list_screens() -> dict[str, Any]:
    screens = []
    for spec in SCREENS.values():
        screens.append(
            {
                "operation": spec.operation,
                "title": spec.title,
                "route": spec.route,
                "table": spec.table,
                "primary_key": spec.pk,
                "write_style": spec.write_style,
                "risk": spec.risk,
                "detail_operation": spec.detail_operation,
                "named_tools": list(spec.named_tools),
                "employee_writes": spec.employee_writes,
            }
        )
    return {
        "ok": True,
        "count": len(screens),
        "screens": screens,
        "details": (
            "These are onboarded grids in the schema catalog. "
            "Use saga_describe_screen(operation) for columns/aliases. "
            "Writes go through named tools only — there is no generic create-row MCP tool."
        ),
    }
