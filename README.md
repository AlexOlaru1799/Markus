# Markus MCP

A local Python MCP server for Cursor (and Codex), hosted in Docker on this Mac.

## Tools

- `health_check`: Returns server status, version, and transport details.
- `list_tools`: Returns the tools exposed by `markus-mcp`.
- `whatsapp_web_status`: Checks whether the single WhatsApp Web session is paired.
- `whatsapp_web_pair`: Keeps WhatsApp Web open and waits for a **live** QR scan.
- `whatsapp_web_pairing_screenshot`: Deprecated; prefer `whatsapp_web_pair`.
- `whatsapp_web_reset_session`: Closes the live browser; optionally deletes the profile.
- `send_whatsapp_message`: Sends via exact chat name (or phone) after confirmation.
- `saga_status` / `saga_login` / `saga_submit_otp` / `saga_reset_session`
- `saga_list_partners` / `saga_search_partners` / `saga_get_partner`
- `saga_create_partner` / `saga_update_partner` (require `confirm_write=true`)

## Run

```bash
cp .env.example .env
# Create private.data with SAGA email on line 1 and password on line 2
docker compose up --build
```

The MCP endpoint will be available at:

```text
http://localhost:8000/mcp
```

`private.data` is gitignored and mounted read-only into the container as
`/app/private.data` (`SAGA_CREDENTIALS_FILE`).

## Project Shape

`server.py` is the MCP router. It owns server creation and tool registration.
Tool implementation code lives under `src/markus_mcp/tools/`.
SAGA WEB helpers live under `src/markus_mcp/tools/saga/`.

## Cursor Config

Add Markus to your Cursor MCP config (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "markus": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Restart Cursor (or reload MCP servers) after editing.

Then ask the agent to call `health_check` or `list_tools` to confirm connectivity.

## Codex Config

Add this to a Codex config file, such as project-scoped `.codex/config.toml`:

```toml
[mcp_servers.markus]
url = "http://localhost:8000/mcp"
startup_timeout_sec = 20
tool_timeout_sec = 240
enabled = true
default_tools_approval_mode = "writes"
```

After adding the config, restart Codex or open a new task in this project. In
Codex, use `/mcp` to confirm the `markus` server is connected, then ask Codex
to call the `health_check` or `list_tools` tool.

## WhatsApp Web

This uses one persisted WhatsApp Web browser session inside Docker. The Chromium
process stays alive across tool calls so QR pairing and sending share the same
live session.

Set these values in `.env`:

```bash
MARKUS_DATA_DIR=/data
MARKUS_HOST_DATA_DIR=/Users/cristianolaru/Desktop/Markus/data
WHATSAPP_HEADLESS=false
WHATSAPP_PAIR_TIMEOUT_SEC=180
```

`/data` is the path inside the Docker container. It is mounted to the local
`./data` folder by `docker-compose.yml`, so browser login state and QR
screenshots survive container restarts:

```text
./data/whatsapp-session              # persisted WhatsApp Web browser profile
./data/screenshots/whatsapp-qr-latest.png  # live QR screenshot while pairing
```

Restart the container after changing `.env`:

```bash
docker compose up -d --build
```

### Pairing (important)

`whatsapp_web_pair` returns quickly with a QR screenshot. The Chromium session stays
open in the background and refreshes `whatsapp-qr-latest.png` while unpaired.

1. Ask the agent to call `whatsapp_web_pair`.
2. Open the returned `screenshot_path` (usually `.../data/screenshots/whatsapp-qr-latest.png`).
3. Scan that QR with your phone (the browser is still running server-side).
4. Ask the agent to poll `whatsapp_web_status` until `paired: true`.
5. If the QR looks stale, call `whatsapp_web_pair` again to refresh, or wait ~15s for the auto refresh.

If pairing is stuck, call `whatsapp_web_reset_session` with `delete_profile=true` and pair again.

### Sending

1. Ask something like: “Message Roberta and tell her I love her.”
2. The agent calls `send_whatsapp_message` with `to_name="Roberta"`, `confirm_send=false`.
3. Markus searches chats/contacts and accepts only a **100% exact** name match
   (trim + case-insensitive). Near matches are refused and nothing is sent.
4. The agent shows you the preview and waits for an explicit “yes, send it.”
5. Only then it calls again with `confirm_send=true`.

Optional: pass `to_phone_number` with country code when you want to skip name search.

## SAGA WEB

SAGA WEB has no public API. Markus keeps a **persistent Chromium profile** under
`./data/saga-session` (same browser for up to ~3 months after email authorization).

```bash
SAGA_CREDENTIALS_FILE=/app/private.data
SAGA_BASE_URL=https://web.sagasoft.ro
SAGA_HEADLESS=false
```

### Login (prefer 3-month browser trust)

1. Ask the agent to call `saga_login`.
2. If `needs_browser_authorization=true`, open the SAGA email and click
   **Autorizează browser** (not “Autentificare fără autorizare”). That trust lasts ~3 months
   for this profile. Then call `saga_login` again.
3. Only if you explicitly want a one-time OTP every login, use
   `saga_login(allow_otp_without_authorization=true)` and then `saga_submit_otp`.
4. Confirm with `saga_status` (`logged_in=true`, ideally `firm_selected=true`).

Do **not** delete `./data/saga-session` and avoid `saga_reset_session(delete_profile=true)`
unless you intentionally want a new browser identity. Container rebuilds keep the profile
as long as the `./data` bind mount remains.

### Partners / clients

- `saga_list_partners` / `saga_search_partners` / `saga_get_partner` are read-only.
- `saga_partner_fields` lists writable Clienti columns and aliases.
- `saga_create_partner` / `saga_update_partner` accept **only the fields you specify**;
  unspecified fields stay blank (create) or unchanged (update). Use either SAGA names
  (`Denumire`, `CodFiscal`, `Judet`, …) or aliases (`denumire`, `cui`, `judet`, …).
- Mutations require a preview call with `confirm_write=false`, then an explicit
  confirmation and `confirm_write=true`.
- Updates require an exact partner id/cod/CUI/name match (no near matches).
