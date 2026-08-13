# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for markus-mcp."""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

# mcp.cli needs typer, which is an extra we neither install nor use; importing it aborts collection.
EXCLUDED = ("mcp.cli",)


def keep_submodule(name):
    return not any(name == mod or name.startswith(mod + ".") for mod in EXCLUDED)


datas = []
binaries = []
hiddenimports = collect_submodules("markus_mcp")

# playwright must ship its node driver so `--setup` can install Chromium without pip.
for pkg in ("mcp", "playwright", "pypdf", "xlrd"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg, filter_submodules=keep_submodule)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

datas.append(
    (
        os.path.join(SRC, "markus_mcp", "agent_skills"),
        os.path.join("markus_mcp", "agent_skills"),
    )
)

a = Analysis(
    [os.path.join(SRC, "markus_mcp", "__main__.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "markus_mcp.server",
        "markus_mcp.bootstrap",
        "markus_mcp.cursor_install",
        "markus_mcp.cursor_skills",
        "markus_mcp.paths",
        "markus_mcp.tools.catalog",
        "markus_mcp.tools.health",
        "markus_mcp.tools.whatsapp_web",
        "markus_mcp.tools.saga.credentials",
        "markus_mcp.tools.saga.session",
        "markus_mcp.tools.saga.partners",
        "markus_mcp.tools.saga.iesiri_valuta",
        "markus_mcp.tools.saga.fx_invoice_pdf",
        "markus_mcp.tools.saga.import_date",
        "markus_mcp.tools.saga.wipe",
        "markus_mcp.tools.smartbill",
        "markus_mcp.tools.smartbill.credentials",
        "markus_mcp.tools.smartbill.status",
        "markus_mcp.tools.smartbill.client",
        "markus_mcp.tools.smartbill.cloud",
        "markus_mcp.tools.smartbill.supplier_docs",
        "markus_mcp.tools.smartbill.saga_xml",
        "markus_mcp.tools.smartbill.xls_read",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mcp.cli", "typer"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="markus-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
