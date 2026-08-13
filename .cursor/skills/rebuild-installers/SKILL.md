---
name: rebuild-installers
description: >-
  Rebuild Markus closed employee installers (.dmg on macOS, .exe on Windows)
  from packaging scripts or GitHub Actions. Use when the user asks to rebuild,
  package, ship, or make the Markus installer, DMG, EXE, Inno Setup, PyInstaller
  binary, or employee distribution.
---

This skill is **repo-only** (rebuild the employee `.dmg` / `.exe`). It is not
copied to `~/.cursor/skills/` for Markus MCP clients.

Run the **existing packaging scripts**. Do not invent a new PyInstaller/Inno flow.

Outputs (do not commit `packaging/dist/`):

- macOS: `packaging/dist/Markus-<version>-macos.dmg`
- Windows: `packaging/dist/MarkusSetup-<version>-win64.exe`

Version comes from `src/markus_mcp/__init__.py` / `pyproject.toml`.

## Checklist

```
- [ ] 1. Confirm host OS vs requested artifact
- [ ] 2. Build binary
- [ ] 3. Wrap installer
- [ ] 4. Report artifact paths
```

## Step 1 — Choose how to build

- **This Mac, `.dmg`:** run local bash scripts (this machine).
- **This Mac, `.exe`:** do **not** run Windows PowerShell locally. Trigger CI
  (preferred) or tell the user they need a Windows box with Inno Setup 6.
- **Both artifacts / no local Windows:** GitHub Actions
  `.github/workflows/build-installers.yml` (`workflow_dispatch` or tag `v*`).

Code signing is optional; skip unless the user asks. Unsigned builds are fine
for internal pilots.

## Step 2 — macOS DMG (local)

From repo root, sequentially:

```bash
packaging/build_binary.sh
packaging/macos/make_dmg.sh
```

Notes:

- Uses project `.venv` (creates Python 3.12 via `uv` if missing).
- Installs `.[packaging]` (PyInstaller) if needed, then Playwright Chromium.
- Binary: `packaging/dist/markus-mcp`
- DMG wraps that binary + `packaging/macos/Install Markus.command`

If `hdiutil` fails, report the error; do not substitute a zip unless asked.

## Step 3 — Windows EXE

**On Windows (PowerShell), from repo root:**

```powershell
.\packaging\build_binary.ps1
.\packaging\windows\build_installer.ps1
```

`build_installer.ps1` rebuilds the binary again, then runs Inno Setup
(`ISCC.exe`). Needs Inno Setup 6, or `ISCC` set to that path.

**From macOS / CI:**

```bash
gh workflow run build-installers.yml
# then: gh run watch
# artifacts: markus-macos-dmg, markus-windows-setup
```

Use `gh` for GitHub. Do not push a tag unless the user asked for a release tag.

## Step 4 — Report

Reply with:

- What was built (dmg / exe / both)
- Full artifact path(s) or Actions artifact names
- Version string
- If Windows was CI-only, say so

Do not copy installers into `~/.markus` or register Cursor MCP unless asked.
That is `markus-mcp --setup` / the DMG installer, not this skill.
