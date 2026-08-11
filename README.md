# Markus MCP

Local Cursor MCP for **SAGA WEB** and **WhatsApp Web**. Each user keeps their own
browser sessions under `~/.markus` (Windows: `%USERPROFILE%\.markus`).

Employees should install from a **closed `.dmg` / `.exe`** — not from this source tree.

## For employees (no source)

1. Get `Markus-*-macos.dmg` or `MarkusSetup-*-win64.exe` from your admin.
2. Run the installer (`Install Markus.command` on macOS) and enter your SAGA email
   and password when prompted.
3. Restart Cursor → **Reload MCP servers**.
4. In Agent chat, ask for `health_check`.
5. Pair WhatsApp: ask for `whatsapp_web_pair`, open the QR screenshot path, scan with your phone.

To change credentials later, rerun the installer or edit `~/.markus/private.data`.

You do not need the Markus git repo.

## For developers (this repo)

```bash
cd /path/to/Markus
python3 -m pip install -e .
python3 -m markus_mcp --setup
# creates ~/.markus, installs Chromium (unless --skip-browser), registers Cursor MCP
```

Or configure `~/.cursor/mcp.json` manually:

```json
{
  "mcpServers": {
    "markus": {
      "command": "python3",
      "args": ["-m", "markus_mcp"],
      "env": { "MARKUS_MCP_TRANSPORT": "stdio" }
    }
  }
}
```

Default transport is **stdio** (Cursor `command` MCP). `MARKUS_HOME`, `MARKUS_DATA_DIR` and
`SAGA_CREDENTIALS_FILE` are resolved from the current user's home at startup, so set them
only to override the defaults.

### Build closed installers

```bash
# macOS
packaging/build_binary.sh
packaging/macos/make_dmg.sh
# → packaging/dist/Markus-<version>-macos.dmg

# Windows (PowerShell + Inno Setup 6)
.\packaging\build_binary.ps1
.\packaging\windows\build_installer.ps1
# → packaging/dist/MarkusSetup-<version>-win64.exe
```

CI: [`.github/workflows/build-installers.yml`](.github/workflows/build-installers.yml) builds both on tag `v*` or workflow_dispatch.

Code signing (Apple Developer ID / Authenticode) is recommended before wide employee rollout; unsigned builds are fine for internal pilots.

## Tools

- Health: `health_check`, `list_tools`
- WhatsApp: `whatsapp_web_status`, `whatsapp_web_pair`, `send_whatsapp_message`, …
- SAGA: `saga_login`, `saga_submit_otp`, partners CRUD, `saga_add_iesiri_valuta`, …

## Data layout

```text
~/.markus/
  private.data          # credentials as `key = value` (saga_username, saga_password, …)
  data/
    whatsapp-session/   # WhatsApp Web profile
    saga-session/       # SAGA WEB profile
    screenshots/        # QR images
    saga/               # SAGA screenshots / captures
```

## WhatsApp / SAGA

Same flows as before: pair WhatsApp via QR screenshot; SAGA prefers email
**Autorizează browser** for ~3 month trust. Mutations require `confirm_write` /
`confirm_send` preview then confirm.
