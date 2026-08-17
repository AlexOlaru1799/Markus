# Accountant pilot — engineer notes

Provisioning (clone, branch `ap/<name>`, Cursor, MCP pointing at this checkout's venv, test-account credentials) is manual. Log Markus into the test SAGA/SmartBill accounts only. Each accountant gets their own `ap/<name>` branch.

1. Install the user-level hooks described in [`.cursor/hooks/README.md`](hooks/README.md).
2. Confirm a fresh Agent chat loads accountant context (plain language, no Git talk).
3. After Markus Python changes, reload MCP. `health_check` includes `source_revision` and `started_at`; if `started_at` is old, reload.

Publishing from the accountant session: `python scripts/accountant-checkpoint.py` (add `--session-end` at end of day). It pushes only the current `ap/<name>` ref. Protect `main` on GitHub; pilot branches are never merged automatically.
