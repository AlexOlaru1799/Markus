from __future__ import annotations

import unittest

from markus_mcp.tools.saga import protocol


class RequestSetupTests(unittest.TestCase):
    def test_paging_and_master_id(self) -> None:
        raw = protocol.request_setup(skip=10, batch_size=25, master_id="42")
        self.assertIn('"Skip":10', raw)
        self.assertIn('"BatchSize":25', raw)
        self.assertIn('"Id":"42"', raw)
        self.assertIn('"GetRowsCount":true', raw)

    def test_keyword_and_no_count(self) -> None:
        raw = protocol.request_setup(keyword="acme", get_rows_count=False, batch_size=0)
        self.assertIn('"FilterKeyword":"acme"', raw)
        self.assertIn('"GetRowsCount":false', raw)
        self.assertIn('"BatchSize":0', raw)

    def test_filter_columns(self) -> None:
        raw = protocol.request_setup(keyword="acme", FilterColumns=["Cod", "Denumire"])
        self.assertIn('"FilterKeyword":"acme"', raw)
        self.assertIn('"FilterColumns":["Cod","Denumire"]', raw)

    def test_rows_count(self) -> None:
        self.assertEqual(protocol.rows_count_from_payload({"rowsCount": 12, "data": []}), 12)
        self.assertEqual(protocol.rows_count_from_payload({"data": {"rowsCount": "3"}}), 3)
        self.assertIsNone(protocol.rows_count_from_payload([{"Cod": "1"}]))


class ClassifyTests(unittest.TestCase):
    def test_validation_numeric_id_is_success(self) -> None:
        result = protocol.classify({"type": "Validation", "status": "12345"})
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.new_id, "12345")

    def test_choice_needs_choice(self) -> None:
        result = protocol.classify({"type": "Choice", "flagId": "abc", "status": "Continuam?"})
        self.assertEqual(result.outcome, "needs_choice")
        self.assertEqual(result.flag_id, "abc")

    def test_warning_is_warning(self) -> None:
        result = protocol.classify({"type": "Warning", "status": "Nu ati ales contul"})
        self.assertEqual(result.outcome, "warning")
        self.assertIn("contul", result.message or "")

    def test_ex_validate_data_is_choice(self) -> None:
        result = protocol.classify(
            {"errorCode": "ValidateData", "validationFlags": [{"id": "f1"}]}
        )
        self.assertEqual(result.outcome, "needs_choice")
        self.assertEqual(result.flag_id, "f1")

    def test_success_true(self) -> None:
        result = protocol.classify({"success": True})
        self.assertEqual(result.outcome, "success")

    def test_delete_empty_body_ok(self) -> None:
        result = protocol.classify({}, ok_http=True, for_delete=True)
        self.assertEqual(result.outcome, "success")

    def test_delete_validation_prompt_needs_check(self) -> None:
        prompted = protocol.classify(
            {"type": "Validation", "status": "Stergeti inregistrarea?"},
            ok_http=True,
            for_delete=True,
        )
        self.assertEqual(prompted.outcome, "needs_check")
        first_succes = protocol.classify(
            {"type": "Validation", "status": "Succes."},
            ok_http=True,
            for_delete=True,
        )
        self.assertEqual(first_succes.outcome, "needs_check")
        confirmed = protocol.classify(
            {"type": "Validation", "status": "Succes."},
            ok_http=True,
            for_delete=True,
            checked=True,
        )
        self.assertEqual(confirmed.outcome, "success")
        deleted = protocol.classify(
            {"type": "Validation", "status": "Deleted succesfully."},
            ok_http=True,
            for_delete=True,
            checked=True,
        )
        self.assertEqual(deleted.outcome, "success")

    def test_http_error(self) -> None:
        result = protocol.classify("nope", ok_http=False)
        self.assertEqual(result.outcome, "error")

    def test_create_first_succes_needs_check(self) -> None:
        first = protocol.classify({"type": "Validation", "status": "Succes."})
        self.assertEqual(first.outcome, "needs_check")
        confirmed = protocol.classify(
            {"type": "Validation", "status": "Succes."},
            checked=True,
        )
        self.assertEqual(confirmed.outcome, "success")

    def test_created_record_id_ignores_partner_cod(self) -> None:
        row = {"Cod": "00003", "NrDoc": "D0006", "Client": "DEMO"}
        self.assertEqual(
            protocol.created_record_id({"type": "Validation", "status": "Succes."}, row),
            "",
        )
        self.assertEqual(
            protocol.created_record_id({"type": "Validation", "status": "611"}, row),
            "611",
        )

    def test_extract_created_ids(self) -> None:
        ids = protocol.extract_created_ids({"type": "Validation", "status": "99"}, {"NrDoc": "K003"})
        self.assertEqual(ids.get("ID_Iesire"), "99")
        self.assertEqual(ids.get("NrDoc"), "K003")


class CoerceTests(unittest.TestCase):
    def test_numeric_and_id_default(self) -> None:
        out = protocol.coerce_row_json({"Cantitate": "2", "TVAI": "0", "Client": "Acme"})
        self.assertEqual(out["Cantitate"], 2.0)
        self.assertEqual(out["TVAI"], 0)
        self.assertEqual(out["Client"], "Acme")
        self.assertEqual(out["Id"], "")


class RowsFromPayloadTests(unittest.TestCase):
    def test_nested_data(self) -> None:
        rows = protocol.rows_from_payload({"data": [{"Cod": "1"}, "skip"]})
        self.assertEqual(rows, [{"Cod": "1"}])

    def test_row_get(self) -> None:
        self.assertEqual(protocol.row_get({"cod": "X"}, "Cod"), "X")


if __name__ == "__main__":
    unittest.main()
