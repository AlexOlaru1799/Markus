# Cursor hooks (engineer installs on the accountant PC)

Repository files here are the contract. Install copies under `%USERPROFILE%\.cursor\` — do not expect project hooks to stay machine-local (they would also run on developer machines).

Copy (on the accountant PC only; see [`.cursor/accountant-pilot-engineer.md`](../accountant-pilot-engineer.md) for the PowerShell commands):

- [`scripts/cursor-hooks/session-start-accountant.ps1`](../../scripts/cursor-hooks/session-start-accountant.ps1) → `%USERPROFILE%\.cursor\hooks\`
- [`scripts/cursor-hooks/before-shell-git.ps1`](../../scripts/cursor-hooks/before-shell-git.ps1) → `%USERPROFILE%\.cursor\hooks\`
- [`scripts/cursor-hooks/pre-tool-use-accountant.ps1`](../../scripts/cursor-hooks/pre-tool-use-accountant.ps1) → `%USERPROFILE%\.cursor\hooks\`
- [`scripts/cursor-hooks/hooks.json.example`](../../scripts/cursor-hooks/hooks.json.example) → `%USERPROFILE%\.cursor\hooks.json`

User-hook commands are relative to `%USERPROFILE%\.cursor\`, so the example file uses `./hooks/….ps1`.

## sessionStart

Injects `.cursor/accountant-context.md` when that file exists in `CURSOR_PROJECT_DIR`. Otherwise it prints `{}`. Install this hook only on the accountant PC.

Stdout must be one JSON object: `{"additional_context": "<string>"}`. Diagnostics go to stderr.

## beforeShellExecution (never ask)

`failClosed: true`. The script returns **allow** or **deny** only — never `ask`, so the accountant is not shown a shell permission card.

- Allows `python scripts/accountant-checkpoint.py` and `python scripts/quality_gate.py`
- Denies raw `git commit` / `push` / checkout / reset / rebase / tag / `--force`
- Denies destructive shell (`rm -rf`, `Remove-Item -Recurse`, `format`, `shutdown`, download-and-`iex`, …)
- Denies a working directory outside the Markus checkout when Cursor provides `cwd`
- Denies Windows config (`reg add`, services, firewall, `ms-settings:`, …)
- Parse failures deny (fail closed)

## preToolUse (never ask)

`failClosed: true`. Allows create/edit/delete **inside** this Markus repository. Denies Write / Delete / StrReplace / ApplyPatch when the path is outside the checkout.

This is accidental-misuse protection, not an OS security boundary. See [`.cursor/accountant-pilot-engineer.md`](../accountant-pilot-engineer.md) for Run Mode and Windows limits.
