from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from markus_mcp.tools.smartbill.saga_xml import write_facturi_xml


class SmartbillXmlTests(unittest.TestCase):
    def test_keeps_nir_non_ro_and_skips_ro(self) -> None:
        records = [
            {
                "NIR": "9001",
                "Document furnizor": "INV-DE-1",
                "CIF": "DE123456",
                "Denumire furnizor": "DEMO SUPPLIER GMBH",
                "Data doc": "15.08.2026",
                "Data scadentei": "30.08.2026",
                "Moneda": "RON",
                "Valoare fara TVA": "100",
                "TVA": "19",
            },
            {
                "NIR": "9002",
                "Document furnizor": "INV-RO-1",
                "CIF": "RO12345678",
                "Denumire furnizor": "SHOULD SKIP SRL",
                "Data doc": "15.08.2026",
                "Data scadentei": "30.08.2026",
                "Moneda": "RON",
                "Valoare fara TVA": "50",
                "TVA": "9.5",
            },
            {
                "NIR": "",
                "Document furnizor": "NO-NIR",
                "CIF": "BG111",
                "Denumire furnizor": "NO NIR",
                "Data doc": "15.08.2026",
                "Valoare fara TVA": "1",
                "TVA": "0",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "F_demo.xml"
            result = write_facturi_xml(records, dest)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["invoice_count"], 1)
            self.assertEqual(result["skipped_ro"], 1)
            self.assertGreaterEqual(result["skipped_no_nir"], 1)
            xml = dest.read_text(encoding="utf-8")
        self.assertIn("DEMO SUPPLIER GMBH", xml)
        self.assertIn("DE123456", xml)
        self.assertNotIn("RO12345678", xml)
        self.assertNotIn("SHOULD SKIP", xml)


if __name__ == "__main__":
    unittest.main()
