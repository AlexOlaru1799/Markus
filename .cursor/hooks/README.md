# Cursor hooks (engineer installs on the accountant PC)

Repository files here are the contract. Install copies under `%USERPROFILE%\.cursor\` — do not expect project hooks to stay machine-local.

## sessionStart

Copy [`scripts/cursor-hooks/session-start-accountant.ps1`](../../scripts/cursor-hooks/session-start-accountant.ps1) next to the user `hooks.json`.

`hooks.json` fragment:

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "command": "powershell -NoProfile -File \"%USERPROFILE%\\.cursor\\hooks\\session-start-accountant.ps1\""
      }
    ]
  }
}
```

The script injects `.cursor/accountant-context.md` when that file exists in `CURSOR_PROJECT_DIR`. Otherwise it prints `{}`. Install this hook only on the accountant PC.

Stdout must be one JSON object: `{"additional_context": "<string>"}`. Diagnostics go to stderr.

## beforeShellExecution (pilot Git)

Install [`scripts/cursor-hooks/before-shell-git.ps1`](../../scripts/cursor-hooks/before-shell-git.ps1) as a `beforeShellExecution` command hook with `failClosed: true`. It denies raw `git commit` / `push` / checkout / reset / rebase / tag / `--force` and allows `python scripts/accountant-checkpoint.py` and `python scripts/quality_gate.py`.
