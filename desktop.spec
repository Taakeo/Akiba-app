# -*- mode: python ; coding: utf-8 -*-
# Build : pyinstaller desktop.spec
#
# Fenêtre native (§2.1, §15.1 spec) : bundle l'application Flask + templates
# + static (CSS déjà compilé, JS, polices vendorisées) dans un .exe unique.
# `tools/tailwindcss.exe` (outil de dev pour compiler le CSS) n'est PAS
# embarqué — seul `app/static/dist/output.css` déjà généré l'est.

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = (
    collect_submodules("sqlcipher3")
    + collect_submodules("win32print")
    + ["win32timezone"]  # requis en silence par certains modules pywin32
)

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app/templates", "app/templates"),
        ("app/static", "app/static"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AKIBA APP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/static/vendor/logo/akiba.ico",
)
