from __future__ import annotations

import unittest

from markus_mcp.tools.catalog import TOOL_CATALOG
from markus_mcp.tools.health import health_check


CORE = {
    "health_check",
    "list_tools",
    "saga_login",
    "saga_add_iesire",
    "saga_add_intrare",
    "saga_post_bank_entries",
    "saga_wipe_data",
    "smartbill_invoices_to_saga_xml",
}


class HealthAndCatalogTests(unittest.TestCase):
    def test_health_fingerprint(self) -> None:
        payload = health_check()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("source_revision", payload)
        self.assertIn("started_at", payload)
        self.assertTrue(payload["started_at"])

    def test_core_tools_registered(self) -> None:
        names = {item.name for item in TOOL_CATALOG}
        missing = CORE - names
        self.assertFalse(missing, missing)
        self.assertGreaterEqual(len(TOOL_CATALOG), 60)


if __name__ == "__main__":
    unittest.main()
