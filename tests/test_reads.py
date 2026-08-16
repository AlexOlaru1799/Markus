from __future__ import annotations

import unittest

from markus_mcp.tools.catalog import TOOL_CATALOG
from markus_mcp.tools.saga import context, exports, lookups, reads, reports, schema


class LookupPathTests(unittest.TestCase):
    def test_conturi_home_first(self) -> None:
        paths = lookups.combo_paths("IesiriValuta", "Conturi")
        self.assertEqual(paths[0], "Home/GetData_ComboBox_Conturi")
        self.assertIn("IesiriValuta/GetData_ComboBox_Conturi", paths)

    def test_tip_controller_first(self) -> None:
        paths = lookups.combo_paths("IesiriValuta", "Tip_Iesiri")
        self.assertEqual(paths[0], "IesiriValuta/GetData_ComboBox_Tip_Iesiri")
        self.assertIn("Home/GetData_ComboBox_Tip_Iesiri", paths)

    def test_resolve_select_model_from_catalog(self) -> None:
        model, column = lookups.resolve_select_model("iesiri_valuta_detalii", "account")
        self.assertEqual(model, "Conturi")
        self.assertEqual((column or {}).get("name"), "Cont")

    def test_unknown_lookup_screen(self) -> None:
        result = lookups.lookup("not_a_screen", "Cont")
        self.assertFalse(result["ok"])
        self.assertIn("clienti", result["screens"])


class ExportSniffTests(unittest.TestCase):
    def test_xlsx_pdf_xls_html_json(self) -> None:
        self.assertEqual(exports.sniff_bytes(b"PK\x03\x04rest"), "xlsx")
        self.assertEqual(exports.sniff_bytes(b"%PDF-1.7"), "pdf")
        self.assertEqual(exports.sniff_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"), "xls")
        self.assertEqual(exports.sniff_bytes(b"  <html><body>error</body></html>"), "html")
        self.assertEqual(exports.sniff_bytes(b'{"error":true}'), "json")
        self.assertEqual(exports.sniff_bytes(b"<?xml version='1.0'?><Facturi/>"), "xml")
        self.assertIsNone(exports.sniff_bytes(b""))

    def test_unknown_export_screen(self) -> None:
        result = exports.export_grid("nope")
        self.assertFalse(result["ok"])
        self.assertIn("screens", result)


class ReadGateTests(unittest.TestCase):
    def test_unknown_list_and_get(self) -> None:
        listed = reads.list_rows("nope")
        self.assertFalse(listed["ok"])
        got = reads.get_row("clienti", "")
        self.assertFalse(got["ok"])
        missing = reads.get_row("nope", "1")
        self.assertFalse(missing["ok"])


class ReportCatalogTests(unittest.TestCase):
    def test_resolve_aliases_and_pack(self) -> None:
        resolved = reports.resolve_report("trial_balance")
        self.assertIsNotNone(resolved)
        report_id, spec = resolved or ("", {})
        self.assertEqual(report_id, "balanta")
        self.assertTrue(spec.get("setter"))
        pack = reports.resolve_report("period_pack")
        self.assertIsNotNone(pack)
        pack_id, pack_spec = pack or ("", {})
        self.assertEqual(pack_id, "period_pack")
        self.assertTrue(pack_spec.get("period_pack_bundle"))

    def test_remaining_reports_have_setters(self) -> None:
        for name in (
            "carte_mare",
            "situatie_furnizori",
            "situatie_clienti",
            "registru_jurnal",
            "situatie_vanzari",
            "situatie_sgr",
            "raport_gestiune",
            "situatie_comenzi",
        ):
            resolved = reports.resolve_report(name)
            self.assertIsNotNone(resolved, name)
            report_id, spec = resolved or ("", {})
            self.assertIsNot(spec.get("captured"), False, name)
            self.assertTrue(spec.get("setter") or spec.get("creators"), name)
            self.assertTrue(spec.get("provisional"), name)

    def test_unknown_report_lists_catalog(self) -> None:
        result = reports.run_report("not-a-report")
        self.assertFalse(result["ok"])
        names = {item["name"] for item in result["reports"]}
        self.assertIn("balanta", names)
        self.assertIn("jurnal_cumparari", names)

    def test_map_report_dates(self) -> None:
        mapped = schema.map_fields("report:balanta", {"from": "2026-08-01", "to": "2026-08-31"})
        self.assertEqual(mapped.fields["DataStart"], "2026-08-01")
        self.assertEqual(mapped.fields["DataStop"], "2026-08-31")
        self.assertEqual(reports.saga_date("2026-08-01"), "01.08.2026")

    def test_list_reports(self) -> None:
        listed = reports.list_reports()
        self.assertTrue(listed["ok"])
        self.assertGreaterEqual(listed["count"], 8)


class ContextNoticeTests(unittest.TestCase):
    def test_closed_period_notice(self) -> None:
        self.assertIsNone(context.closed_period_notice(None))
        self.assertIsNone(context.closed_period_notice({}))
        self.assertIn("closed period", context.closed_period_notice(True) or "")
        self.assertIn("closed period", context.closed_period_notice({"Luna": "7", "An": "2026"}) or "")


class DescribeLookupsTests(unittest.TestCase):
    def test_describe_exposes_select_model(self) -> None:
        described = schema.describe_screen("iesiri_valuta")
        self.assertTrue(described["ok"])
        lookups_by_field = {item["field"]: item for item in described["lookups"]}
        self.assertEqual(lookups_by_field["Valuta"]["select_model"], "Valute")
        line = {item["field"]: item for item in described["line_lookups"]}
        self.assertEqual(line["Cont"]["select_model"], "Conturi")
        self.assertEqual(line["Cont"]["paths"][0], "Home/GetData_ComboBox_Conturi")


class CatalogTests(unittest.TestCase):
    def test_wave1_and_wave2_tools(self) -> None:
        names = {tool.name for tool in TOOL_CATALOG}
        for name in (
            "saga_list_rows",
            "saga_get_row",
            "saga_lookup",
            "saga_export_grid",
            "saga_run_report",
            "saga_efactura_list",
            "saga_close_month",
        ):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()
