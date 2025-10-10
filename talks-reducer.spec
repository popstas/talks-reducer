# -*- mode: python ; coding: utf-8 -*-

import os
import pathlib
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

PROJECT_DIR = pathlib.Path(__file__).resolve().parent

# Data files bundled with the GUI
base_datas = [
    (PROJECT_DIR / "talks_reducer" / "resources" / "icons" / "app-256.png", "talks_reducer/resources/icons"),
    (PROJECT_DIR / "talks_reducer" / "resources" / "icons" / "app.ico", "talks_reducer/resources/icons"),
    (PROJECT_DIR / "talks_reducer" / "resources" / "icons" / "app.icns", "talks_reducer/resources/icons"),
]

datas = [(str(src), dest) for src, dest in base_datas if src.exists()]

try:
    datas.extend(collect_data_files("gradio_client"))
except Exception:
    pass

hiddenimports = ["tkinterdnd2"]
hiddenimports.extend(collect_submodules("talks_reducer"))

DEFAULT_EXCLUDES = [
    "PySide6",
    "PyQt5",
    "PyQt6",
    "pandas",
    "matplotlib",
    "numba",
    "cupy",
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "tensorboard",
    "fsspec",
    "setuptools",
    "pkg_resources",
    "wheel",
    "importlib_metadata",
    "zipp",
    "platformdirs",
    "jaraco.functools",
    "jaraco.text",
    "backports",
    "win32com.test",
]

EXTRA_EXCLUDES = [
    value.strip()
    for value in os.environ.get("PYINSTALLER_EXTRA_EXCLUDES", "").split(",")
    if value.strip()
]

excludes = DEFAULT_EXCLUDES + EXTRA_EXCLUDES

pathex = [str(PROJECT_DIR)]

icon_file = None
if sys.platform == "darwin":
    candidate = PROJECT_DIR / "talks_reducer" / "resources" / "icons" / "app.icns"
elif sys.platform.startswith("win"):
    candidate = PROJECT_DIR / "talks_reducer" / "resources" / "icons" / "app.ico"
else:
    candidate = PROJECT_DIR / "talks_reducer" / "resources" / "icons" / "app.ico"

if candidate.exists():
    icon_file = str(candidate)

version_file = None
if sys.platform.startswith("win"):
    candidate_version = PROJECT_DIR / "version.txt"
    if candidate_version.exists():
        version_file = str(candidate_version)

a = Analysis(
    ["launcher.py"],
    pathex=pathex,
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="talks-reducer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=version_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="talks-reducer",
)
