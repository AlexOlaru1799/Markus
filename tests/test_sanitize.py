from __future__ import annotations

import unittest

from markus_mcp.sanitize import is_forbidden_path, sanitize_label, secret_assignment_lines


class SanitizeTests(unittest.TestCase):
    def test_forbidden_paths(self) -> None:
        self.assertTrue(is_forbidden_path("private.data"))
        self.assertTrue(is_forbidden_path("/Users/x/.markus/data/saga-session/Default"))
        self.assertFalse(is_forbidden_path("src/markus_mcp/pilot_branch.py"))

    def test_secret_lines(self) -> None:
        text = "saga_password = 'hunter2'\n# comment\n"
        self.assertTrue(secret_assignment_lines(text))
        self.assertFalse(secret_assignment_lines("firm_code = '20119775'\n"))

    def test_sanitize_label(self) -> None:
        self.assertEqual(sanitize_label("RO12345678"), "CIF-DEMO")
        self.assertEqual(sanitize_label("Acme SRL"), "DEMO")


if __name__ == "__main__":
    unittest.main()
