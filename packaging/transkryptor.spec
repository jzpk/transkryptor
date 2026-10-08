# -*- mode: python ; coding: utf-8 -*-
"""Specyfikacja PyInstallera dla artefaktów wydania (faza 05).

Plik jest celowo cienki: wszystkie decyzje o zawartości artefaktu żyją
w ``transkryptor.packaging.bundle`` i są objęte testami. Tryb onedir jest
wymagany — biblioteki Qt muszą zostać osobnymi plikami dynamicznymi, żeby
użytkownik mógł je podmienić (LGPL-3.0).

Uruchomienie bezpośrednie (zwykle wywoływane przez
``python -m transkryptor.packaging``):

    uv run --group packaging pyinstaller packaging/transkryptor.spec --noconfirm
"""

import sys
from pathlib import Path

SOURCE_ROOT = Path(SPECPATH).resolve().parent / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from transkryptor.packaging.bundle import analysis_options  # noqa: E402

options = analysis_options(sys.platform)

analysis = Analysis(
    options["scripts"],
    pathex=options["pathex"],
    binaries=[],
    datas=options["datas"],
    hiddenimports=options["hiddenimports"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=options["excludes"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=options["name"],
    debug=False,
    bootloader_ignore_signals=False,
    strip=options["strip"],
    upx=options["upx"],
    console=options["console"],
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=options["icon"],
)

# COLLECT (onedir) zamiast onefile: Qt pozostaje wymienialnymi bibliotekami.
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=options["strip"],
    upx=options["upx"],
    name=options["name"],
)
