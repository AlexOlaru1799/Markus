from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from markus_mcp.tools.catalog import TOOL_CATALOG
from markus_mcp.tools.saga import bank, invoices, nomenclator, schema
from markus_mcp.tools.saga.documents.emit_incasari_xml import emit_incasari_xml
from markus_mcp.tools.saga.documents.parse_facturi_xml import parse_facturi_xml
from markus_mcp.tools.saga.documents.parse_incasari_xml import parse_incasari_xml
from markus_mcp.tools.saga.documents.types import bank_bundle


class NomenclatorPreviewTests(unittest.TestCase):
    def test_supplier_preview_and_unknown(self) -> None:
        preview = nomenclator.create_record(
            "furnizori",
            {"name": "ACME FURN SRL", "cui": "12345678"},
            noun="supplier",
            confirm_write=False,
        )
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview["mapped_fields"]["Denumire"], "ACME FURN SRL")
        self.assertEqual(preview["mapped_fields"]["CodFiscal"], "12345678")

        unknown = nomenclator.create_record(
            "furnizori",
            {"name": "X", "mystery": "nope"},
            noun="supplier",
            confirm_write=False,
        )
        self.assertFalse(unknown["ok"])
        self.assertIn("mystery", unknown.get("unknown_fields") or [])

    def test_item_requires_denumire(self) -> None:
        result = nomenclator.create_record("articole", {"cod": "A1"}, noun="item")
        self.assertIn("Denumire", result.get("missing_required") or [])

    def test_casa_preview(self) -> None:
        preview = bank.add_casa_entry(
            {"date": "15.08.2026", "amount": "100", "account": "5311"},
            confirm_write=False,
        )
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview["mapped_fields"]["Suma"], "100")
        self.assertEqual(preview["mapped_fields"]["Cont"], "5311")
        self.assertEqual(preview.get("screen"), "registru_casa")

    def test_casa_fx_routes_to_valuta(self) -> None:
        preview = bank.add_casa_entry(
            {"date": "15.08.2026", "amount": "100", "account": "5311", "valuta": "EUR"},
            confirm_write=False,
        )
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview.get("screen"), "registru_casa_valuta")
        self.assertEqual(preview["mapped_fields"]["Valuta"], "EUR")
        self.assertIn("Curs", preview.get("auto_filled") or {})


class InvoicePreviewTests(unittest.TestCase):
    def test_add_iesire_preview(self) -> None:
        result = invoices.add_iesire(
            header={"customer": "Nord", "invoice_date": "15.08.2026", "number": "K003"},
            lines=[{"item_name": "Transport", "qty": "1", "price": "100", "account": "704", "vat_rate": "21"}],
            confirm_write=False,
        )
        self.assertTrue(result.get("requires_confirmation"))
        self.assertEqual(result["screen"], "iesiri")
        self.assertEqual(result["mapped"]["header"]["Client"], "Nord")
        self.assertEqual(result["mapped"]["lines"][0]["Cont"], "704")
        self.assertEqual(result.get("ensure_partner", {}).get("role"), "clienti")
        self.assertEqual(result.get("ensure_partner", {}).get("query"), "Nord")

    def test_fx_routes_to_iesiri_valuta(self) -> None:
        result = invoices.add_iesire(
            header={"client": "Nord", "valuta": "EUR", "data": "15.08.2026"},
            lines=[{"cont": "704", "cantitate": "1", "pret_unitar_valuta": "10"}],
            confirm_write=False,
        )
        self.assertTrue(result.get("requires_confirmation"))
        self.assertEqual(result.get("screen"), "iesiri_valuta")
        self.assertEqual(result.get("action"), "add_iesire")
        self.assertEqual(result["mapped"]["header"]["Valuta"], "EUR")
        self.assertEqual(result.get("ensure_partner", {}).get("role"), "clienti")

        named = __import__(
            "markus_mcp.tools.saga.iesiri_valuta", fromlist=["create_fx_invoice"]
        ).create_fx_invoice(
            {"client": "Nord", "valuta": "EUR", "data": "15.08.2026"},
            [{"cont": "704", "cantitate": "1", "pret_unitar_valuta": "10"}],
            confirm_write=False,
        )
        self.assertEqual(named.get("action"), "create_fx_invoice")
        self.assertEqual(named.get("screen"), "iesiri_valuta")
        self.assertEqual(named["mapped"]["header"], result["mapped"]["header"])
        self.assertEqual(named["mapped"]["lines"], result["mapped"]["lines"])

    def test_add_intrare_maps_supplier(self) -> None:
        result = invoices.add_intrare(
            header={"FurnizorNume": "Vendor SRL", "FacturaData": "01.08.2026", "FacturaNumar": "F9"},
            lines=[{"Descriere": "Marfa", "Cantitate": "2", "Pret": "50", "Cont": "371"}],
            confirm_write=False,
        )
        self.assertTrue(result.get("requires_confirmation"))
        self.assertEqual(result["screen"], "intrari")
        self.assertEqual(result["mapped"]["header"]["Furnizor"], "Vendor SRL")
        self.assertEqual(result["mapped"]["header"]["NrDoc"], "F9")
        self.assertEqual(result.get("ensure_partner", {}).get("role"), "furnizori")
        self.assertEqual(result["mapped"]["lines"][0]["PretUnitar"], "50")

    def test_line_missing_cont(self) -> None:
        result = invoices.add_iesire(
            header={"client": "A", "data": "15.08.2026"},
            lines=[{"denumire": "X", "cantitate": "1"}],
            confirm_write=False,
        )
        self.assertFalse(result["ok"])
        self.assertIn("Cont", result.get("error") or "")


class BankEmitTests(unittest.TestCase):
    def test_emit_and_parse_roundtrip(self) -> None:
        document = bank_bundle(
            kind="Incasari",
            account="5121",
            entries=[{"Data": "15.08.2026", "NrDoc": "OP1", "Suma": "121", "Cont": "5121", "FacturaNumar": "K003"}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = emit_incasari_xml(document, dest=Path(tmp) / "I_test.xml")
            parsed = parse_incasari_xml(path)
        self.assertEqual(parsed["kind"], "Incasari")
        self.assertEqual(parsed["document"]["entries"][0]["NrDoc"], "OP1")

    def test_post_requires_entries(self) -> None:
        result = bank.post_bank_entries(document={"kind": "bank_receipts"})
        self.assertFalse(result["ok"])

    def test_fx_bank_preview_screen(self) -> None:
        document = bank_bundle(
            kind="Incasari",
            account="5124",
            entries=[
                {
                    "Data": "15.08.2026",
                    "NrDoc": "OP1",
                    "Suma": "100",
                    "Cont": "5124",
                    "Moneda": "EUR",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = emit_incasari_xml(document, dest=Path(tmp) / "I_15_08_2026.xml")
            document["meta"] = {"source_path": str(path)}
            preview = bank.post_bank_entries(document=document, confirm_write=False)
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview.get("screen"), "jurnal_banca_valuta")
        self.assertEqual(preview.get("currency"), "EUR")


class ParityTests(unittest.TestCase):
    def test_xml_and_chat_map_to_same_iesiri_fields(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Facturi>
  <Factura>
    <Antet>
      <FacturaNumar>K003</FacturaNumar>
      <FacturaData>15.08.2026</FacturaData>
      <ClientNume>FAKE NORD LOGISTICS</ClientNume>
      <ClientCod>C001</ClientCod>
      <FacturaMoneda>RON</FacturaMoneda>
    </Antet>
    <Linie>
      <Descriere>Transport</Descriere>
      <Cantitate>1</Cantitate>
      <Pret>100</Pret>
      <Valoare>100</Valoare>
      <TVAProc>21</TVAProc>
      <Cont>704</Cont>
    </Linie>
  </Factura>
</Facturi>
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F_test.xml"
            path.write_text(xml, encoding="utf-8")
            parsed = parse_facturi_xml(path)
        doc = parsed["documents"][0]
        hand_header = schema.map_fields(
            "iesiri",
            {"ClientNume": "FAKE NORD LOGISTICS", "ClientCod": "C001", "FacturaNumar": "K003", "FacturaData": "15.08.2026"},
        )
        hand_line = schema.map_fields(
            "iesiri_detalii",
            {"Descriere": "Transport", "Cantitate": "1", "Pret": "100", "Cont": "704", "TVAProc": "21"},
        )
        self.assertEqual(doc["header"]["NrDoc"], hand_header.fields["NrDoc"])
        self.assertEqual(doc["header"]["Client"], hand_header.fields["Client"])
        self.assertEqual(doc["lines"][0]["Cont"], hand_line.fields["Cont"])
        self.assertEqual(doc["lines"][0]["PretUnitar"], hand_line.fields["PretUnitar"])
        preview = invoices.add_iesire(document=doc, confirm_write=False)
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview["mapped"]["header"]["NrDoc"], "K003")
        self.assertEqual(preview["mapped"]["header"]["Client"], "FAKE NORD LOGISTICS")
        self.assertEqual(preview["mapped"]["lines"][0]["Cont"], "704")


class CatalogTests(unittest.TestCase):
    def test_wave3_to_5_tools(self) -> None:
        names = {tool.name for tool in TOOL_CATALOG}
        for name in (
            "saga_create_supplier",
            "saga_create_item",
            "saga_chart_of_accounts",
            "saga_add_iesire",
            "saga_add_intrare",
            "saga_post_bank_entries",
            "saga_add_casa_entry",
            "saga_add_iesiri_valuta",
            "saga_validate_document",
        ):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
