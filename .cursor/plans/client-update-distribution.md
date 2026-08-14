# Markus client update & distribution options

## Problem

Today employees install from closed `.dmg` / `.exe` (PyInstaller binary + setup). Every bug fix means rebuilding installers and manually sending them to each client. There is no release feed, no in-place binary update, and no package-manager channel.

Current install targets:

- macOS: `~/.markus/bin/markus-mcp`
- Windows: `%LOCALAPPDATA%\Markus\markus-mcp.exe`
- Side effects of `--setup`: Chromium (~150MB), `~/.cursor/mcp.json`, skills under `~/.cursor/skills/`, credentials under `~/.markus`

Version source of truth: `src/markus_mcp/__init__.py` / `pyproject.toml` (today `0.7.0`). CI builds on tag `v*` but does not publish a client-facing update channel.

## Constraints that shape the options

1. **Closed binary, not source.** Employees must not need the git repo or a Python toolchain.
2. **stdio MCP.** Cursor launches a local command; the update story is “replace that binary (+ skills)”, not “push a web deploy”.
3. **Heavy first install, light updates.** Chromium + credentials + MCP registration are mostly one-time. Day-to-day fixes usually only need a new `markus-mcp` binary and refreshed skills.
4. **Private distribution.** Artifacts should not be world-public unless you accept that.
5. **Signing.** Auto-download makes Apple notarization / Authenticode more important than ad-hoc pilot builds.

## Options

### A. Private release channel (same installers, better delivery)

**What:** CI publishes versioned artifacts to GitHub Releases (private repo), S3/R2, or a simple download portal. Clients always get the latest from one URL / Slack pin / internal page.

**Pros:** Smallest change; reuses existing DMG/EXE pipeline; clear version history.

**Cons:** Still manual reinstall per machine; you still ship full installers for tiny fixes.

**Fit:** Immediate relief while you design real updates.

### B. Thin updater + keep installers for first install (recommended direction)

**What:**

1. First install stays DMG/EXE (Chromium, mcp.json, credentials, skills).
2. Publish a **manifest** next to binaries, e.g.:

   ```json
   {
     "version": "0.7.1",
     "published_at": "2026-08-14T12:00:00Z",
     "channel": "stable",
     "macos": { "url": "...", "sha256": "..." },
     "windows": { "url": "...", "sha256": "..." },
     "skills_version": "0.7.1"
   }
   ```

3. Add `markus-mcp --update` (and optionally a quiet check on MCP startup / `health_check`) that:
   - fetches the manifest over HTTPS
   - downloads the platform binary if newer
   - verifies checksum (and signature later)
   - atomically replaces the installed binary
   - re-copies agent skills from the new bundle (or a skills tarball)
   - does **not** re-download Chromium or wipe `~/.markus` sessions

**Pros:** Bug fixes become “run update” or automatic; installers become rare; matches how the product is actually laid out on disk.

**Cons:** Needs a hosted feed + auth story for private builds; signing/notarization matters; must handle Windows file locks if Cursor still has the MCP process open (update on next restart is the usual pattern).

**Auth patterns for private artifacts:** signed download URLs, GitHub token in `~/.markus`, or company SSO front door. Prefer short-lived signed URLs over shipping a long-lived GitHub PAT to every laptop.

### C. Package managers (Homebrew / winget)

**What:** Private Homebrew tap and/or winget/Chocolatey package that upgrades the binary.

**Pros:** Familiar to IT; `brew upgrade markus` / `winget upgrade Markus`.

**Cons:** Poor fit for typical non-technical employees; private taps still need hosting + auth; Windows winget private feeds are heavier than a custom `--update`; does not help Cursor skill refresh unless the formula/package runs post-install hooks.

**Fit:** Only if clients are IT-managed fleets that already use these tools.

### D. Always-latest launcher

**What:** Installed command is a tiny stub that downloads/runs the current binary each Cursor session (or caches with TTL).

**Pros:** Clients never think about versions.

**Cons:** Startup latency and network dependency; harder offline use; more failure modes in Cursor MCP launch; overkill if you already have B.

**Fit:** Rarely worth it for a local automation MCP.

### E. Python/pip private index

**What:** Publish `markus-mcp` to a private PyPI and have clients `pipx upgrade`.

**Pros:** Natural for Python apps.

**Cons:** Conflicts with the closed-employee / no-toolchain goal; Playwright/Chromium still need managing; not what installers were built for.

**Fit:** Developers only (already covered by editable install).

### F. Remote MCP / hosted service

**What:** Move logic to a server so “update” = deploy backend.

**Pros:** Instant updates for all clients.

**Cons:** Wrong shape today: SAGA/WhatsApp/SmartBill sessions, screenshots, and credentials are per-user local browser profiles under `~/.markus`. Hosting that centrally is a product rewrite (auth, multi-tenant browsers, compliance), not a distribution tweak.

**Fit:** Long-term product rethink, not an installer replacement.

## Practical recommendation

| Horizon | Move |
|--------|------|
| Now | **A** — tag releases, publish both installers (+ raw binaries) to a private feed; one “latest” link for admins/clients |
| Next | **B** — ship raw `markus-mcp` artifacts + manifest; add `--update` / restart-friendly auto-check; keep DMG/EXE for bootstrap only |
| Later | Code signing + notarization; optional `stable` / `beta` channels; health_check reports “update available” |
| Skip unless requirements change | C, D, E, F as the primary path |

## What must version together

An update is not only the binary:

1. `markus-mcp` executable
2. Bundled / copied **agent skills** under `~/.cursor/skills/`
3. Manifest / `__version__` so `health_check` shows the running version
4. Optionally a min-schema note if `private.data` keys change (prefer backward-compatible credential files)

Chromium and browser profiles should stay put across updates unless Playwright major bumps require a browser reinstall (`--setup` / explicit “repair”).

## Minimal architecture for B

```text
CI (tag v*):
  build macOS binary + DMG
  build Windows binary + EXE
  upload:
    markus-mcp-macos
    markus-mcp-win64.exe
    Markus-<ver>-macos.dmg
    MarkusSetup-<ver>-win64.exe
    manifest.json (stable)
Client:
  first run → installer
  later     → markus-mcp --update  (or prompt via health_check)
```

Replace-in-place paths already used by installers:

- `~/.markus/bin/markus-mcp`
- `%LOCALAPPDATA%\Markus\markus-mcp.exe`

## Option B deep dive

### Why this fits Markus specifically

Installers already separate **bootstrap** from **runtime**:

| First install (keep DMG/EXE) | Later updates (new path) |
|------------------------------|--------------------------|
| Copy binary into fixed path | Replace that same binary |
| `markus-mcp --setup` (dirs, Chromium ~150MB, mcp.json, skills) | Re-copy skills from new binary; skip Chromium |
| Prompt for SAGA / SmartBill credentials | Leave `~/.markus/private.data` alone |
| Browser profiles under `~/.markus/data/*-session/` | Leave sessions alone |

Cursor’s `mcp.json` already points at the fixed binary path (`command` = installed exe). After an in-place replace, **no mcp.json edit is required** — Reload MCP servers is enough.

Skills are already overwrite-safe: `install_cursor_skills()` copies bundled `agent_skills/*/SKILL.md` into `~/.cursor/skills/` and overwrites same-named skills. A frozen binary can call that after self-replace (or from the new process on first start).

### End-to-end flow

```text
You tag v0.7.1
  → CI builds PyInstaller binaries (+ still builds DMG/EXE for new hires)
  → uploads:
      releases/0.7.1/markus-mcp-macos
      releases/0.7.1/markus-mcp-win64.exe
      releases/0.7.1/Markus-0.7.1-macos.dmg          # optional, bootstrap only
      releases/0.7.1/MarkusSetup-0.7.1-win64.exe
      releases/stable/manifest.json                   # pointer to current stable

Employee machine (already installed 0.7.0):
  markus-mcp --update
    1. GET manifest.json
    2. compare manifest.version vs __version__
    3. if newer: download platform binary to *.tmp
    4. sha256 verify
    5. atomic rename over installed path
       (Windows: may need pending-replace / apply on next start if file locked)
    6. clear quarantine + ad-hoc codesign on macOS (same as Install Markus.command)
    7. run skills install from the new binary
    8. print “Updated 0.7.0 → 0.7.1; reload MCP in Cursor”
```

### Manifest shape (concrete)

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

`min_updater_version` lets you force a full reinstall if the updater protocol itself changes.

### Client UX tiers (pick one)

1. **Manual only** — document `markus-mcp --update` (mac Terminal / Win Start menu shortcut). Simplest; still better than redistributing installers.
2. **health_check hint** — return `update_available`, `latest_version`, `notes` so the agent/user sees it in chat. No auto-download.
3. **Auto-check on startup** — once per day, fetch manifest; if newer, either notify or download to a staging file and apply on next clean start. Best UX; needs careful Windows locking.

Recommended rollout: ship (1)+(2) first; add (3) once checksum + hosting are proven.

### What the updater must NOT do

- Re-run full `--setup` by default (would re-touch Chromium and feel like a reinstall)
- Wipe WhatsApp / SAGA / SmartBill session dirs
- Re-prompt credentials
- Require admin rights (installers already use user-local paths: `~/.markus`, `%LOCALAPPDATA%\Markus`)

Exception: if Playwright major bumps and Chromium is incompatible, expose `markus-mcp --repair-browser` (existing `--setup` Chromium path) rather than folding that into every update.

### Platform gotchas

**macOS**

- DMG copies today clear quarantine + ad-hoc `codesign -`. The updater must do the same after download or Gatekeeper may `Killed: 9`.
- For wider rollout, Developer ID + notarization beats ad-hoc signing once downloads are automatic.
- Binary path has **no spaces** by design (`~/.markus/bin/markus-mcp`) because Cursor splits command paths on whitespace.

**Windows**

- While Cursor has the MCP server running, `markus-mcp.exe` is locked. Pattern: download to `markus-mcp.exe.new`, write a marker, replace on next cold start before serving MCP — or tell the user to Reload/quit Cursor first and replace immediately.
- Inno install dir is already per-user (`PrivilegesRequired=lowest`), so updates do not need elevation.

### Hosting & auth

| Hosting | Auth for private clients | Notes |
|---------|--------------------------|-------|
| GitHub Releases (private repo) | GitHub token or release-asset proxy you control | Easy with current CI; shipping PATs to laptops is awkward |
| S3 / R2 / GCS | CloudFront signed URLs or short-lived tokens | Cleanest for `--update`; CI uploads on tag |
| Internal HTTPS (company site) | VPN / SSO cookie / basic auth | Fine if clients are always on corp network |

Prefer: CI uploads binaries + writes `manifest.json`; clients only need the **manifest URL** baked into the binary (or in `~/.markus/update.url`). Do not bake long-lived cloud secrets into the employee binary.

### CI changes (relative to today)

Today `.github/workflows/build-installers.yml` uploads Actions artifacts only (DMG/EXE). For B it should also:

1. Upload **raw** `packaging/dist/markus-mcp` and `markus-mcp.exe` (not only the wrappers).
2. Publish to the chosen host on tag `v*`.
3. Generate/update `manifest.json` with version from `__init__.py`, URLs, sha256.
4. Keep DMG/EXE publishing for **new** employees and disaster recovery.

### Failure modes to design for

- Offline / corporate proxy → update fails soft; MCP keeps running old version
- Partial download → never replace until sha256 matches
- Rollback → keep previous binary as `markus-mcp.bak` for one generation
- Skills copy fails → still report binary updated; tell user to run `--register-cursor` / repair
- Manifest newer but URL 404 → do not corrupt install

### Effort shape (technical, not calendar)

- **Small:** CLI `--update` + manifest fetch + atomic replace + skills refresh
- **Medium:** CI publish raw binaries + manifest; `health_check` update fields; Windows pending-replace
- **Larger:** signed URLs / private auth; notarization; silent daily check; beta channel

No change to SAGA/WhatsApp/SmartBill tool code is required for the updater itself.

## Decision checklist (when implementing)

- [ ] Where do private artifacts live? (GitHub Releases vs S3/R2 vs internal HTTPS)
- [ ] How do client machines authenticate downloads?
- [ ] Manual `--update` only, or also check on startup / health_check?
- [ ] Update while MCP is running: defer replace until process exit?
- [ ] Skills always overwrite on update?
- [ ] Signed builds required before enabling auto-download?
- [ ] Channels: one `stable`, or also `beta`?

## Non-goals for a first updater

- Replacing Cursor itself
- Re-prompting SAGA credentials on every update
- Re-downloading Chromium on every update
- Public unauthenticated binaries (unless you explicitly choose that)
