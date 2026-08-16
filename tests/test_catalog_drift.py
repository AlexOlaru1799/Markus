from __future__ import annotations

import json
import unittest
from pathlib import Path

from markus_mcp.tools.saga import discovery, schema


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "probe_clienti.json"


class CatalogDriftTests(unittest.TestCase):
    def test_clienti_fixture_matches_catalog(self) -> None:
        probe = json.loads(FIXTURE.read_text(encoding="utf-8"))
        diff = discovery.diff_probe("clienti", probe)
        self.assertTrue(diff["ok"], diff)
        self.assertEqual(diff["missing_in_catalog"], [])
        self.assertEqual(diff["extra_in_catalog"], [])
        self.assertIn("Denumire", diff["matched"])
        catalog = set(schema.column_map("clienti"))
        self.assertEqual(set(diff["matched"]), catalog)

    def test_live_extra_column_is_drift(self) -> None:
        probe = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cols = probe["live"]["primary"]["tableModel"]["columns"]
        cols.append({"name": "MysteryCol", "inputType": "text"})
        diff = discovery.diff_probe("clienti", probe)
        self.assertFalse(diff["ok"])
        self.assertIn("MysteryCol", diff["missing_in_catalog"])
        self.assertEqual(diff["extra_in_catalog"], [])

    def test_subset_fixture_is_catalog_extra(self) -> None:
        probe = json.loads(FIXTURE.read_text(encoding="utf-8"))
        probe["live"]["primary"]["tableModel"]["columns"] = [
            {"name": "Cod", "inputType": "text"},
            {"name": "Denumire", "inputType": "text"},
        ]
        diff = discovery.diff_probe("clienti", probe)
        self.assertIn("CodFiscal", diff["extra_in_catalog"])
        self.assertEqual(diff["missing_in_catalog"], [])


if __name__ == "__main__":
    unittest.main()
