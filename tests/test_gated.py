from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from markus_mcp.tools.catalog import TOOL_CATALOG
from markus_mcp.tools.saga import context, declarations, efactura, fx_invoice_pdf, grid, partners, registry, schema, validate_doc
from markus_mcp.tools.saga.documents.emit_facturi_xml import emit_facturi_xml
from markus_mcp.tools.saga.documents.parse_facturi_xml import parse_facturi_xml


class RegistryWave6Tests(unittest.TestCase):
    def test_stock_and_nomenclator_screens_are_read_only(self) -> None:
        listed = registry.list_screens()
        ops = {item["operation"]: item for item in listed["screens"]}
        for name in (
            "agenti",
            "imobilizari",
            "transferuri",
            "bonuri",
            "productie",
            "inventariere",
            "efactura",
            "numere_serii",
            "salariati",
        ):
            self.assertIn(name, ops)
            self.assertFalse(ops[name]["employee_writes"])
        described = schema.describe_screen("imobilizari")
        self.assertTrue(described["ok"])
        self.assertIn("NrInventar", {item["name"] for item in described["fields"]})


class GatedPreviewTests(unittest.TestCase):
    def test_set_interval_preview(self) -> None:
        preview = context.set_interval("2026-08-01", "2026-08-31", confirm_write=False)
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview["preview"]["interval_start"], "01.08.2026")
        self.assertEqual(preview["preview"]["interval_end"], "31.08.2026")

    def test_close_month_refuses_wrong_phrase(self) -> None:
        result = context.close_month(confirm_write=True, confirm_phrase="yes")
        self.assertFalse(result["ok"])
        self.assertIn("INCHIDE LUNA", result.get("error") or "")

    def test_efactura_submit_preview_and_phrase(self) -> None:
        preview = efactura.submit_invoice("IDX1", confirm_write=False)
        self.assertTrue(preview.get("requires_confirmation"))
        refused = efactura.submit_invoice("IDX1", confirm_write=True, confirm_phrase="ok")
        self.assertFalse(refused["ok"])
        self.assertIn("TRIMITE EFACTURA", refused.get("error") or "")
        cancelled = efactura.cancel_invoice("IDX1", confirm_write=True, confirm_phrase="no")
        self.assertIn("ANULEAZA EFACTURA", cancelled.get("error") or "")

    def test_validate_document_preview(self) -> None:
        preview = validate_doc.validate_document("iesiri", "ID1", confirm_write=False)
        self.assertTrue(preview.get("requires_confirmation"))
        self.assertEqual(preview.get("action"), "validate_document")
        unlocked = validate_doc.validate_document(
            "iesiri", "ID1", devalidate=True, confirm_write=False
        )
        self.assertEqual(unlocked.get("action"), "devalidate_document")

    def test_submit_declaration_preview_and_phrase(self) -> None:
        preview = declarations.submit_declaration("406", confirm_write=False)
        self.assertTrue(preview.get("requires_confirmation"))
        refused = declarations.submit_declaration("406", confirm_write=True, confirm_phrase="ok")
        self.assertFalse(refused["ok"])
        self.assertIn("TRIMITE DECLARATIE", refused.get("error") or "")
        listed = declarations.generate_declaration("")
        names = {item["name"] for item in listed["declarations"]}
        self.assertIn("406", names)
        self.assertIn("revisal", names)


class EmitFacturiTests(unittest.TestCase):
    def test_roundtrip_sales_invoice(self) -> None:
        document = {
            "kind": "sales_invoice",
            "currency": "RON",
            "header": {"Client": "FAKE NORD LOGISTICS", "Cod": "C001", "NrDoc": "K003", "Data": "15.08.2026"},
            "lines": [{"Denumire": "Transport", "Cantitate": "1", "PretUnitar": "100", "Cont": "704", "TVA_ART": "21"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = emit_facturi_xml(document, dest=Path(tmp) / "F_emit.xml")
            parsed = parse_facturi_xml(path)
        self.assertEqual(parsed["documents"][0]["header"]["NrDoc"], "K003")
        self.assertEqual(parsed["documents"][0]["header"]["Client"], "FAKE NORD LOGISTICS")
        self.assertEqual(parsed["documents"][0]["lines"][0]["Cont"], "704")


class CatalogWave678Tests(unittest.TestCase):
    def test_gated_tools_registered(self) -> None:
        names = {tool.name for tool in TOOL_CATALOG}
        for name in (
            "saga_about",
            "saga_set_interval",
            "saga_close_month",
            "saga_efactura_list",
            "saga_efactura_download",
            "saga_efactura_submit",
            "saga_efactura_cancel",
            "saga_generate_declaration",
            "saga_submit_declaration",
            "saga_validate_document",
        ):
            self.assertIn(name, names)


class WritePreflightTests(unittest.TestCase):
    def test_assert_writable_does_not_veto_closed_month(self) -> None:
        from unittest.mock import patch

        page = object()
        allowed = {"ok": True, "rights": [{"Ecran": "Clienti", "Adaugare": "1"}]}
        with patch.object(context, "load_rights", return_value=allowed):
            self.assertIsNone(context.assert_writable(page, screen="clienti"))
        denied = {"ok": True, "rights": [{"Ecran": "Clienti", "Adaugare": "0"}]}
        with patch.object(context, "load_rights", return_value=denied):
            blocked = context.assert_writable(page, screen="clienti")
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["blocked"], "rights")

    def test_period_is_closed(self) -> None:
        self.assertTrue(context.period_is_closed(True))
        self.assertTrue(context.period_is_closed("da"))
        self.assertTrue(context.period_is_closed({"Luna": "07.2026"}))
        self.assertFalse(context.period_is_closed(None))
        self.assertFalse(context.period_is_closed("0"))
        self.assertFalse(context.period_is_closed({}))

    def test_screen_write_denied_matches_route_and_explicit_deny(self) -> None:
        rights = [{"Ecran": "Clienti", "Adaugare": "0"}]
        self.assertTrue(context.screen_write_denied(rights, "clienti"))
        self.assertTrue(
            context.screen_write_denied(
                {"Drepturi": [{"Controller": "JurnalDeBanca", "Salvare": "nu"}]},
                "jurnal_banca",
            )
        )
        self.assertFalse(context.screen_write_denied([{"Ecran": "Clienti", "Access": "0"}], "clienti"))
        self.assertTrue(context.screen_write_denied([{"Ecran": "Clienti", "Access": "1"}], "clienti"))
        self.assertFalse(context.screen_write_denied(rights, "iesiri"))
        self.assertFalse(context.screen_write_denied(rights, ""))

    def test_get_pk_matches_identity_only(self) -> None:
        row = {"Cod": "99", "Denumire": "1", "CodFiscal": "1", "Id": "7"}
        self.assertFalse(grid.row_matches_pk(row, "1", primary_key="Cod"))
        self.assertTrue(grid.row_matches_pk({"Cod": "1", "Denumire": "ACME"}, "1", primary_key="Cod"))
        self.assertTrue(grid.row_matches_pk({"Id": "1", "Denumire": "ACME"}, "1", primary_key="Cod"))

    def test_fx_pdf_helper_names_add_iesiri_valuta(self) -> None:
        source = inspect.getsource(fx_invoice_pdf.parse_fx_invoice_pdf)
        self.assertIn("saga_add_iesiri_valuta", source)
        self.assertNotIn("saga_create_fx_invoice", source)

    def test_partner_write_skips_ui_on_preflight_block(self) -> None:
        blocked = partners._preflight_write_block(
            {
                "ok": False,
                "outcome": "error",
                "blocked": "closed_period",
                "response": {
                    "ok": False,
                    "error": "SAGA working interval is a closed month",
                    "blocked": "closed_period",
                    "screen": "clienti",
                },
            }
        )
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["blocked"], "closed_period")
        self.assertFalse(blocked["ok"])
        self.assertIsNone(
            partners._preflight_write_block(
                {"ok": False, "outcome": "error", "response": {"type": "Validation"}}
            )
        )
        self.assertIsNone(partners._preflight_write_block({"ok": False, "outcome": "error"}))
        delete_block = partners._preflight_write_block(
            {"ok": False, "error": "denied", "blocked": "rights", "screen": "clienti"}
        )
        self.assertEqual(delete_block["blocked"], "rights")


if __name__ == "__main__":
    unittest.main()
