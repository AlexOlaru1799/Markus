# Implement in-place Markus client updater

**Status:** planned (implement later)  
**Decision:** Option B — keep `.dmg` / `.exe` for first install only; ship a private release manifest + `markus-mcp --update` that replaces the binary and refreshes skills in place.

Related context (rejected alternatives): package managers, always-download launcher, private pip, and remote MCP are **out of scope**. See git history of this file / earlier PR discussion if needed.

---

## Goal

After the first employee install, bug fixes must not require redistributing full installers. Clients pick up new versions by updating the already-installed binary at:

- macOS: `~/.markus/bin/markus-mcp`
- Windows: `%LOCALAPPDATA%\Markus\markus-mcp.exe`

Cursor `mcp.json` keeps pointing at that path; users only **Reload MCP servers**.

## Non-goals

- Replacing Cursor
- Re-prompting credentials on update
- Re-downloading Chromium on every update
- Wiping WhatsApp / SAGA / SmartBill sessions under `~/.markus/data/`
- Public unauthenticated binaries (unless explicitly chosen later)
- Auto-download on every MCP startup in v1 (notify via `health_check` first)
- Homebrew / winget / remote hosted MCP

## Decided defaults (for implementation)

| Topic | Decision |
|-------|----------|
| First install | Unchanged: DMG / Inno EXE + `--setup` |
| Update trigger (v1) | `markus-mcp --update` + `health_check` reports availability |
| Auto-apply on startup | **Deferred** to a later phase |
| Skills on update | Always overwrite same-named client skills (existing `install_cursor_skills()`) |
| Channels (v1) | Single `stable` channel |
| Binary replace while running | Prefer immediate replace when unlocked; else stage `*.new` + apply on next cold start / `--update --apply-pending` |
| Rollback | Keep one previous binary as `*.bak` |
| Manifest URL | Bake default URL into binary; allow override via `~/.markus/update.url` or env `MARKUS_UPDATE_URL` |
| Auth (v1 default) | **TBD before coding publish step** — prefer object storage + HTTPS (optionally signed URLs) over shipping GitHub PATs to laptops |
| Code signing | Ad-hoc macOS clear-quarantine/codesign on update (match installer); full Developer ID / Authenticode is a follow-up |

Open before Phase 2 publish work:

- [ ] Artifact host: S3/R2/GCS vs GitHub Releases vs internal HTTPS
- [ ] How private downloads authenticate (signed URL, SSO, VPN-only, token file)

---

## Architecture

```text
Tag vX.Y.Z
  → CI builds PyInstaller binaries + DMG/EXE (bootstrap still published)
  → uploads raw binaries + installers
  → writes releases/stable/manifest.json

Installed client
  markus-mcp --update
    GET manifest
    if newer → download → sha256 → replace binary → install skills
    print reload instructions

health_check
  optionally GET manifest (cached ~1h) → update_available / latest_version / notes
```

### Manifest schema (v1)

```json
{
  "schema": 1,
  "channel": "stable",
  "version": "0.7.1",
  "published_at": "2026-08-14T12:00:00Z",
  "notes": "Fix SmartBill export timeout",
  "macos": {
    "url": "https://downloads.example/markus/0.7.1/markus-mcp-macos",
    "sha256": "…",
    "size": 12345678
  },
  "windows": {
    "url": "https://downloads.example/markus/0.7.1/markus-mcp-win64.exe",
    "sha256": "…",
    "size": 12345678
  },
  "min_updater_version": "0.7.0"
}
```

If running version `< min_updater_version`, instruct a full installer reinstall instead of `--update`.

---

## Implementation phases

### Phase 0 — Prep (no client behavior change)

- [ ] Confirm artifact host + auth model; document URL pattern in this plan
- [ ] Ensure version is single-sourced (`__init__.py` / `pyproject.toml`; keep `markus.iss` in sync or generate it)
- [ ] Extend CI to **also** upload raw binaries as Actions artifacts (macOS `markus-mcp`, Windows `markus-mcp.exe`) alongside DMG/EXE — even before public/private publish
- [ ] Add packaging notes to README: bootstrap vs update

**Files likely touched:** `.github/workflows/build-installers.yml`, `README.md`, optionally `packaging/windows/markus.iss` version sync

### Phase 1 — Client updater (works against a local/fixture manifest)

- [ ] Add `src/markus_mcp/update.py` (or `updater/`) with:
  - resolve manifest URL (env → `~/.markus/update.url` → baked default)
  - fetch + parse manifest (`schema == 1`)
  - semver/version compare vs `__version__`
  - download to temp / `markus-mcp.new`
  - sha256 verify
  - backup current → `.bak`, replace target path
  - macOS: `xattr` clear quarantine + ad-hoc `codesign` (subprocess, best-effort like installer)
  - call `install_cursor_skills()` from the **new** process when possible
  - soft-fail offline / bad network (non-zero exit for CLI; never corrupt binary)
- [ ] Wire CLI in `server.py` `main()`: `--update`, `--check-update` (print JSON, no download)
- [ ] Windows pending replace: if exe locked, leave `.new` + marker file under Markus dir; on next `--update` or dedicated apply path, finish swap when unlocked
- [ ] Unit tests with local HTTP fixture / temp dirs (no real network in CI unit tests)
- [ ] Dev mode: if not frozen, `--update` should error clearly (“updater is for installed binaries”) or update only skills from the checkout — prefer clear error for v1

**Files likely touched:**

- `src/markus_mcp/update.py` (new)
- `src/markus_mcp/server.py` (CLI flags)
- `src/markus_mcp/tools/health.py` (optional fields once check exists)
- `src/markus_mcp/paths.py` (helpers for install binary path if missing)
- tests under `tests/` (create if needed)

### Phase 2 — Publish pipeline

- [ ] On tag `v*`, publish to chosen host:
  - `markus-mcp-macos`
  - `markus-mcp-win64.exe`
  - `Markus-<ver>-macos.dmg`
  - `MarkusSetup-<ver>-win64.exe`
  - `manifest.json` for `stable` (and versioned copy under `releases/<ver>/`)
- [ ] Generate sha256 + embed absolute HTTPS URLs in manifest
- [ ] Bake default manifest URL into the binary (build-time constant or env compiled in packaging scripts)
- [ ] Document employee update steps in README (“For employees” section)

**Files likely touched:** `.github/workflows/build-installers.yml` (or new `publish-release.yml`), `packaging/build_binary.*`, README

### Phase 3 — Discoverability

- [ ] Extend `health_check` with:
  - `version` (already present)
  - `update_available` (bool | null if check skipped/failed)
  - `latest_version`, `update_notes`, `update_error` (optional)
- [ ] Cache manifest check on disk (`~/.markus/update-check.json`) with TTL (~1 hour) so chat health checks are cheap
- [ ] Windows Start Menu / macOS note: optional “Update Markus” helper script next to installers (nice-to-have)
- [ ] Employee README: after bugfix, run update + Reload MCP; new hires still use DMG/EXE

### Phase 4 — Hardening (follow-ups)

- [ ] Code signing / notarization for downloaded binaries
- [ ] Optional `beta` channel via `~/.markus/update.channel`
- [ ] Silent daily check + staged download (still apply on explicit update or clean start)
- [ ] `markus-mcp --repair-browser` alias for Chromium reinstall without full conceptual “reinstall Markus”
- [ ] Rollback command: `markus-mcp --rollback` restores `.bak` if present

---

## Updater must not

1. Call full `bootstrap(install_browser=True)` by default
2. Modify `private.data` credentials
3. Delete `~/.markus/data/*-session/`
4. Require Administrator / root
5. Replace the binary before sha256 matches
6. Leave a half-written executable as the live path (write temp → fsync → rename / pending apply)

---

## Acceptance criteria

### v1 (Phases 0–3)

- [ ] New employee can still install from DMG/EXE and pass `health_check`
- [ ] Existing employee on N can run `markus-mcp --update`, land on N+1, see new `__version__` in `health_check`
- [ ] Skills from N+1 appear under `~/.cursor/skills/` after update
- [ ] Credentials and browser sessions survive the update
- [ ] `mcp.json` command path unchanged; Reload MCP is sufficient
- [ ] Failed download / bad hash leaves previous binary runnable
- [ ] Offline `--update` fails with a clear message; does not break MCP
- [ ] CI tag build publishes manifest + raw binaries + installers to the chosen host
- [ ] README documents first install vs update

### Explicitly not required for v1

- Auto-update without user action
- Notarized / Authenticode-signed update payloads
- Multiple channels

---

## Test plan (when implementing)

1. **Unit:** manifest parse, version compare, sha256 mismatch refusal, skills refresh mocked
2. **macOS integration (manual):** install 0.x DMG → publish newer manifest locally (Python http.server or fixture) → `--update` → quarantine/codesign → Cursor reload → `health_check`
3. **Windows integration (manual):** same with exe lock (Cursor running) → verify pending `.new` behavior → quit/reload → apply
4. **CI:** workflow dry-run on `workflow_dispatch` uploads artifacts; tag publish only when host credentials present

---

## Employee UX (target copy)

**First time:** get DMG/EXE from admin → run installer → enter credentials → restart Cursor → `health_check`.

**Later updates:** admin ships a new release (no file email required) → employee runs `markus-mcp --update` (or follows prompt from `health_check`) → Reload MCP servers → `health_check` shows new version.

---

## Implementation notes (repo anchors)

| Concern | Existing code |
|---------|----------------|
| Version | `src/markus_mcp/__init__.py` |
| Setup / Chromium | `src/markus_mcp/bootstrap.py` |
| mcp.json registration | `src/markus_mcp/cursor_install.py` |
| Skills overwrite | `src/markus_mcp/cursor_skills.py` |
| CLI entry | `src/markus_mcp/server.py` `main()` |
| macOS install copy | `packaging/macos/Install Markus.command` |
| Windows install path | `packaging/windows/markus.iss` (`DefaultDirName={localappdata}\Markus`) |
| CI | `.github/workflows/build-installers.yml` |

No SAGA / WhatsApp / SmartBill tool changes required for the updater itself.
