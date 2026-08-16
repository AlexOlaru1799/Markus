---
name: export-saga-period-pack
description: >-
  Download a SAGA WEB period pack (balanță, jurnal cumpărări, jurnal vânzări,
  and optional fișe conturi) for the connected firm's working interval via
  Markus MCP saga_run_report and saga_context. Use when the user asks for
  reports, situatii, balanta, jurnale, fise conturi, a month pack, or to
  export the current SAGA period as PDF/XLS.
---

# Export SAGA period pack

Use Markus MCP (`user-markus`). Credentials stay in `private.data`.

This job **reads** reports. It does not post invoices or wipe data.

Files land under `~/.markus/data/saga/reports/` only when the download is a
real PDF or Excel file (magic bytes). HTML error pages are not saved.

## Checklist

```
- [ ] 1. saga_status / saga_login (pause for email auth / OTP if needed)
- [ ] 2. saga_context — show firm_name, interval_start/interval_end, closed_period_warning
- [ ] 3. If closed_period_warning is set, tell the user. Still run reports; do not write into a closed month.
- [ ] 4. saga_run_report(name="period_pack") — or the three reports below
- [ ] 5. If the user named accounts → saga_run_report(name="fise_conturi", accounts="401") per account
         (or period_pack with accounts="401,4111")
- [ ] 6. Show each path / kind / size. If a report failed, show error + sniffed type; do not invent a PDF.
```

Equivalent separate calls (same interval defaults):

- `saga_run_report(name="balanta")`
- `saga_run_report(name="jurnal_cumparari")`
- `saga_run_report(name="jurnal_vanzari")`

Optional filters: `from` / `to` (or `DataStart` / `DataStop`) as `dd.mm.yyyy` or `YYYY-MM-DD`.
If omitted, Markus uses the toolbar working interval from `saga_context`.

`format` defaults to `pdf`. Pass `format="xlsx"` when they want Excel.

`saga_run_report(name="")` lists catalog reports. Names with `captured=false`
cannot run until a print-modal auxiliar capture is reviewed.

Bilanț (`name="bilant"`) is **local PDF only**. Do not submit it to ANAF.

Do not call `saga_reset_session` with `delete_profile=true`.

If `list_tools` is missing `saga_run_report`, restart Markus MCP (or bump
`MARKUS_MCP_CATALOG` in `~/.cursor/mcp.json`). After a Markus upgrade, run
`markus-mcp --setup` so this skill is copied to `~/.cursor/skills/`.
