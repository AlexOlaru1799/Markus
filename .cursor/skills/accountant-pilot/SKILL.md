---
name: accountant-pilot
description: >-
  Accountant testing Markus in Cursor. Use when the user says "I am an
  accountant", reports a SAGA/SmartBill flow that is wrong, half-right, or
  missing, or is running an accountant-pilot checkout. Speak in plain
  accounting language; turn valid corrections into tests and small Markus fixes
  without regressions.
---

# Accountant pilot

Read and follow [`.cursor/accountant-context.md`](../../accountant-context.md).

Do the requested flow with Markus tools first. On correction: verify it, add sanitized evidence under `tests/accountant_scenarios/`, fix Markus, run `python scripts/quality_gate.py`, ask them to reload Markus MCP, then retry.

Publish only with `python scripts/accountant-checkpoint.py` on the current `ap/<name>` branch.
