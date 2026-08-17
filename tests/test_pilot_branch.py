from __future__ import annotations

import unittest

from markus_mcp.pilot_branch import is_accountant_pilot_branch


class PilotBranchTests(unittest.TestCase):
    def test_accepts_any_accountant_slug(self) -> None:
        for name in (
            "ap/laurentiu",
            "ap/maria",
            "ap/x",
            "ap/ana-popescu",
        ):
            self.assertTrue(is_accountant_pilot_branch(name), name)

    def test_rejects_non_pilot_and_nested(self) -> None:
        for name in (
            "",
            "main",
            "master",
            "laurentiu/accountant-pilot",
            "accountant-pilot/laurentiu",
            "ap",
            "ap/",
            "ap/foo/bar",
            "feature/ap",
            "ap/..",
        ):
            self.assertFalse(is_accountant_pilot_branch(name), name)


if __name__ == "__main__":
    unittest.main()
