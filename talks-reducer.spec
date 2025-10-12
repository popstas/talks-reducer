# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
import pathlib
import platform
import subprocess
import sys
import sysconfig

try:
    from PyInstaller.building.osx import BUNDLE
except Exception:  # pragma: no cover - macOS-only helper may not import elsewhere
    BUNDLE = None

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

PROJECT_DIR = pathlib.Path(__name__).resolve().parent
if not PROJECT_DIR.exists() and "__file__" in globals():
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


def resolve_app_version() -> str:
    """Return the Talks Reducer version for bundle metadata."""

    about_path = PROJECT_DIR / "talks_reducer" / "__about__.py"
    try:
        spec = importlib.util.spec_from_file_location("talks_reducer.__about__", about_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            version = getattr(module, "__version__", "")
            if version:
                return str(version)
    except Exception:
        pass

    return "0.0.0"


def detect_macos_target_arch() -> str:
    """Derive the most compatible macOS target architecture for PyInstaller."""

    host_arch = platform.machine().lower()
    host_target = None
    if host_arch in {"arm64", "aarch64"}:
        host_target = "arm64"
    elif host_arch in {"x86_64", "amd64"}:
        host_target = "x86_64"

    python_shared_lib = None
    lib_name = sysconfig.get_config_var("LDLIBRARY") or ""
    lib_dir = sysconfig.get_config_var("LIBDIR") or ""
    if lib_name and lib_dir:
        candidate_path = pathlib.Path(lib_dir) / lib_name
        if candidate_path.exists():
            python_shared_lib = candidate_path

    if python_shared_lib is not None:
        try:
            lipo_info = subprocess.check_output(
                ["lipo", "-info", str(python_shared_lib)],
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            lipo_info = ""

        if "Architectures in the fat file" in lipo_info:
            return "universal2"
        if "Non-fat file" in lipo_info and host_target:
            return host_target

    if host_target:
        return host_target

    return "universal2"


target_arch = None
if sys.platform == "darwin":
    target_arch = detect_macos_target_arch()
    print(f"🎯 macOS build target architecture: {target_arch}")

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
    target_arch=target_arch,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=version_file,
)
if sys.platform == "darwin" and BUNDLE is not None:
    app_version = resolve_app_version()
    bundle_identifier = "com.popstas.talks-reducer"
    info_plist = {
        "CFBundleName": "Talks Reducer",
        "CFBundleDisplayName": "Talks Reducer",
        "CFBundleIdentifier": bundle_identifier,
        "CFBundleVersion": app_version,
        "CFBundleShortVersionString": app_version,
        "CFBundlePackageType": "APPL",
        "NSHighResolutionCapable": True,
    }

    app = BUNDLE(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        name="talks-reducer.app",
        icon=icon_file,
        bundle_identifier=bundle_identifier,
        info_plist=info_plist,
        version=app_version,
    )
else:
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
