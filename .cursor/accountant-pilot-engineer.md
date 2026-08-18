# Accountant pilot — engineer notes

Provisioning (clone, branch `ap/<name>`, Cursor, MCP pointing at this checkout's venv, test-account credentials) is manual. Log Markus into the test SAGA/SmartBill accounts only. Each accountant gets their own `ap/<name>` branch.

Do **not** use the closed `.exe` employee installer. The pilot needs this git checkout.

## First install (engineer, on the accountant Windows PC)

Do this in order. GitHub must already have the pilot branch (`ap/<name>`) with this work pushed.

1. **Windows user** — dedicated non-admin login. Install Git, Python 3.11 or 3.12, and Cursor for that user. Open only the Markus clone in Cursor (not Documents or Desktop).
2. **Clone and branch** (PowerShell, GitHub auth as needed):

   ```powershell
   cd $env:USERPROFILE
   git clone https://github.com/AlexOlaru1799/Markus.git
   cd Markus
   git checkout ap/<name>
   ```

   Use the real slug (`ap/laurentiu`, …). Create the branch on GitHub first if it does not exist.

3. **Python venv + Markus MCP** (from the clone):

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python -m pip install -U pip
   .\.venv\Scripts\pip install -e .
   .\.venv\Scripts\python -m markus_mcp --setup
   ```

   `--setup` creates `%USERPROFILE%\.markus`, installs Chromium, registers Cursor MCP against **this** `.venv` Python, and copies agent skills. Enter **test** SAGA (and SmartBill) credentials only — never production. Confirm `%USERPROFILE%\.cursor\mcp.json` `command` is the clone’s `.venv\Scripts\python.exe`.

4. **Hooks** — copy the three scripts and `hooks.json` as in [Hooks](#hooks) below. Fully quit and reopen Cursor. **Settings → Hooks** must show `sessionStart`, `beforeShellExecution`, `preToolUse`.

5. **Cursor Run Mode** — **Settings → Agents → Approvals & Execution → Run Everything**. Leave **File-Deletion Protection** and **External-File Protection** on. Do not use Auto-review (it can still pop Allow/Deny cards).

6. **Reload MCP** — Command Palette → **Reload MCP servers**. In Agent chat: `health_check` (ok, `source_revision` present), then `saga_login` on the test firm (OTP / “Autorizează browser” if SAGA asks).

7. **Accountant-mode check** — new Agent chat. They can say **I am an accountant**. Reply should be accounting language (preview, not Git). Point them at [`.cursor/accountant-quickstart.md`](accountant-quickstart.md) only.

8. **Git on this PC** — set `user.name` / `user.email` for checkpoint commits. They publish with `python scripts/accountant-checkpoint.py` (agent does this; `--session-end` at end of day). Protect `main` on GitHub; never merge pilot branches automatically.

## Machine

No VM. A dedicated non-admin Windows login is enough if the PC is modest. Open only the Markus clone in Cursor (not Documents, Desktop, or other folders).

Do **not** give them the closed `.exe` employee installer. The pilot needs this git checkout. Test SAGA/SmartBill accounts only. Never production credentials or production documents.

The agent may and should change **anything inside this Markus repo**. Restrictions apply only **outside** the checkout (the rest of the accountant PC, and Windows itself). Hooks **deny** destructive shell, Windows config commands, and writes/deletes whose path is outside the repo. Text rules are best-effort; hooks are the mechanical layer. Leave **File-Deletion Protection** and **External-File Protection** enabled in Cursor (they still allow in-repo edits).

## Cursor Run Mode (no permission cards)

On that PC: **Settings → Agents → Approvals & Execution → Run Mode → Run Everything**.

The accountant must not be asked to judge shell/MCP Allow/Deny cards. Ordinary agent work then runs without those prompts.

Also leave **File-Deletion Protection** and **External-File Protection** enabled in the same settings page. Those are extra Cursor layers; they are not a substitute for the hooks below.

Windows has **no** Cursor seatbelt/Landlock sandbox (that exists on macOS/Linux). Run Everything therefore has full shell access unless hooks deny a command. Do not treat Auto-review as the accountant mode: its classifier can still pop an approval card.

## Hooks

Do this **on the accountant Windows PC**, logged in as that user, after the Markus clone exists. User hooks live under `%USERPROFILE%\.cursor\` (not in the git repo).

In PowerShell, set `$repo` to the clone path, then:

```powershell
$repo = "C:\Users\laurentiu\Markus"
$cursor = Join-Path $env:USERPROFILE ".cursor"
$hookDir = Join-Path $cursor "hooks"
New-Item -ItemType Directory -Force -Path $hookDir | Out-Null
Copy-Item (Join-Path $repo "scripts\cursor-hooks\session-start-accountant.ps1") $hookDir -Force
Copy-Item (Join-Path $repo "scripts\cursor-hooks\before-shell-git.ps1") $hookDir -Force
Copy-Item (Join-Path $repo "scripts\cursor-hooks\pre-tool-use-accountant.ps1") $hookDir -Force
Copy-Item (Join-Path $repo "scripts\cursor-hooks\hooks.json.example") (Join-Path $cursor "hooks.json") -Force
```

If `%USERPROFILE%\.cursor\hooks.json` already has other hooks, do not overwrite it — merge the two entries from `scripts/cursor-hooks/hooks.json.example`.

Fully quit and reopen Cursor. Confirm **Settings → Hooks** shows `sessionStart`, `beforeShellExecution`, and `preToolUse`.

The hooks never return `ask`:

1. sessionStart injects accountant context (including “this PC” limits).
2. beforeShellExecution auto-allows safe work, **denies** destructive shell, Windows config, and raw Git publish (`failClosed: true`).
3. preToolUse allows in-repo create/edit/delete and **denies** writes whose path is outside the Markus folder.

## Check after install

1. Fresh Agent chat: ordinary accounting language, no Git talk.
2. Agent can run `python scripts/quality_gate.py` without a permission card.
3. A dummy `Remove-Item -Recurse` / `rm -rf` is denied (agent is told no; accountant is not asked).
4. A write or delete outside the Markus folder is denied.

## Day-to-day

After Markus Python changes, reload MCP. `health_check` includes `source_revision` and `started_at`; if `started_at` is old, reload.

Publishing: `python scripts/accountant-checkpoint.py` (add `--session-end` at end of day). It pushes only the current `ap/<name>` ref. Protect `main` on GitHub; pilot branches are never merged automatically.

SAGA writes still use the chat preview (`confirm_write`): that is an accounting check (does this factură look right?), not a Cursor command permission.
