from __future__ import annotations

import unittest

from markus_mcp.tools.catalog import TOOL_CATALOG
from markus_mcp.tools.saga import registry, schema


class SchemaMapTests(unittest.TestCase):
    def test_partner_aliases_and_unknown(self) -> None:
        mapped = schema.map_fields(
            "clienti",
            {"name": "ACME SRL", "cui": "123", "mystery": "nope"},
        )
        self.assertEqual(mapped.fields["Denumire"], "ACME SRL")
        self.assertEqual(mapped.fields["CodFiscal"], "123")
        self.assertEqual(mapped.unknown, ["mystery"])

    def test_required_on_create(self) -> None:
        mapped = schema.map_fields("clienti", {"cod": "C1"}, required_on_create=True)
        self.assertIn("Denumire", mapped.missing_required)

    def test_fx_header_and_line_aliases(self) -> None:
        header = schema.map_fields(
            "iesiri_valuta",
            {"customer": "Nord", "currency": "EUR", "invoice_date": "01.08.2026"},
        )
        self.assertEqual(header.fields["Client"], "Nord")
        self.assertEqual(header.fields["Valuta"], "EUR")
        self.assertEqual(header.fields["Data"], "01.08.2026")

        line = schema.map_fields(
            "iesiri_valuta_detalii",
            {"qty": "2", "price_fx": "100", "account": "704", "vat_rate": "21"},
        )
        self.assertEqual(line.fields["Cantitate"], "2")
        self.assertEqual(line.fields["PretUnitarValuta"], "100")
        self.assertEqual(line.fields["Cont"], "704")
        self.assertEqual(line.fields["TVA_ART"], "21")
        self.assertEqual(line.missing_required, [])

    def test_line_missing_cont(self) -> None:
        line = schema.map_fields("iesiri_valuta_detalii", {"qty": "1"}, required_on_create=True)
        self.assertIn("Cont", line.missing_required)

    def test_xml_tags_map_to_iesiri(self) -> None:
        mapped = schema.map_fields(
            "iesiri",
            {"ClientNume": "Foo", "FacturaNumar": "F1", "FacturaData": "02.02.2026"},
        )
        self.assertEqual(mapped.fields["Client"], "Foo")
        self.assertEqual(mapped.fields["NrDoc"], "F1")
        self.assertEqual(mapped.fields["Data"], "02.02.2026")
        self.assertEqual(mapped.unknown, [])

    def test_supplier_and_purchase_aliases(self) -> None:
        supplier = schema.map_fields("furnizori", {"name": "Vendor SRL", "cui": "RO1"})
        self.assertEqual(supplier.fields["Denumire"], "Vendor SRL")
        self.assertEqual(supplier.fields["CodFiscal"], "RO1")
        purchase = schema.map_fields(
            "intrari",
            {"FurnizorNume": "Vendor SRL", "FacturaNumar": "F9", "FacturaData": "01.08.2026"},
        )
        self.assertEqual(purchase.fields["Furnizor"], "Vendor SRL")
        self.assertEqual(purchase.fields["NrDoc"], "F9")

    def test_plan_conturi_aliases(self) -> None:
        mapped = schema.map_fields(
            "plan_conturi",
            {"account": "60013", "name": "DEMO CONT", "tip": "A"},
            required_on_create=True,
        )
        self.assertEqual(mapped.fields["Cont"], "60013")
        self.assertEqual(mapped.fields["Denumire"], "DEMO CONT")
        self.assertEqual(mapped.fields["Tip"], "A")
        self.assertEqual(mapped.missing_required, [])

    def test_describe_matches_named_catalogs(self) -> None:
        partners = schema.describe_screen("clienti")
        names = {item["name"] for item in partners["fields"]}
        self.assertIn("Denumire", names)
        self.assertIn("CodFiscal", names)
        self.assertTrue(partners["ok"])

        fx = schema.describe_screen("iesiri_valuta")
        header_names = {item["name"] for item in fx["header_fields"]}
        line_names = {item["name"] for item in fx["line_fields"]}
        self.assertIn("Valuta", header_names)
        self.assertIn("Cont", line_names)

        suppliers = schema.describe_screen("furnizori")
        self.assertTrue(suppliers["ok"])
        self.assertIn("Denumire", {item["name"] for item in suppliers["fields"]})


class RegistryTests(unittest.TestCase):
    def test_list_screens(self) -> None:
        listed = registry.list_screens()
        ops = {item["operation"] for item in listed["screens"]}
        self.assertIn("clienti", ops)
        self.assertIn("iesiri_valuta", ops)
        self.assertIn("furnizori", ops)
        self.assertIn("articole", ops)
        self.assertIn("intrari", ops)
        self.assertIn("registru_casa", ops)
        self.assertIn("jurnal_banca_valuta", ops)
        self.assertIn("registru_casa_valuta", ops)
        self.assertIn("deconturi_valuta", ops)
        self.assertTrue(listed["ok"])
        casa = registry.get_screen("RegistruCasa")
        self.assertIsNotNone(casa)
        self.assertEqual(casa.operation, "registru_casa")
        banca = registry.get_screen("JurnalDeBanca")
        self.assertIsNotNone(banca)
        self.assertEqual(banca.operation, "jurnal_banca")


class CatalogTests(unittest.TestCase):
    def test_new_read_tools_are_registered(self) -> None:
        names = {tool.name for tool in TOOL_CATALOG}
        for name in (
            "saga_context",
            "saga_list_screens",
            "saga_describe_screen",
            "saga_parse_facturi_xml",
            "saga_parse_incasari_xml",
            "saga_list_rows",
            "saga_run_report",
            "saga_add_iesire",
            "saga_add_iesiri_valuta",
        ):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
