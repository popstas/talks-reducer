# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
import pathlib
import platform
import subprocess
import sys
import sysconfig
import ctypes.util

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


def _collect_tcl_tk_data() -> list[tuple[str, str]]:
    """Locate Tcl/Tk resource directories that PyInstaller may miss on macOS."""

    resources: list[tuple[str, str]] = []

    try:
        import tkinter  # type: ignore
    except Exception:
        return resources

    tk_root = pathlib.Path(tkinter.__file__).resolve().parent
    search_roots: set[pathlib.Path] = set()

    # Include sibling directories such as tcl8.6, tk8.6, etc.
    for pattern in ("tcl*", "tk*"):
        for candidate in tk_root.glob(pattern):
            if candidate.is_dir():
                search_roots.add(candidate)

    # Some Python builds stash the resources in a Resources/lib folder.
    potential_parent = tk_root.parent
    if potential_parent.exists():
        for subdir in ("tcl", "tk"):
            container = potential_parent / subdir
            if not container.exists():
                continue
            for candidate in container.glob(f"{subdir}*"):
                if candidate.is_dir():
                    search_roots.add(candidate)

    # Honour environment overrides if present during the build.
    for env_var in ("TCL_LIBRARY", "TK_LIBRARY"):
        value = os.environ.get(env_var)
        if value:
            path = pathlib.Path(value)
            if path.exists():
                search_roots.add(path)
                if path.parent.exists():
                    search_roots.add(path.parent)

    collected: set[str] = set()
    for directory in search_roots:
        if not directory.is_dir():
            continue

        name = directory.name
        if name in collected:
            continue

        if name.lower().startswith("tcl"):
            destination = f"tcl/{name}"
        elif name.lower().startswith("tk"):
            destination = f"tk/{name}"
        else:
            destination = f"tk/{name}"

        resources.append((str(directory), destination))
        collected.add(name)

    return resources


if sys.platform == "darwin":
    datas.extend(_collect_tcl_tk_data())

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

binaries: list[tuple[str, str]] = []
if sys.platform == "darwin":
    lib_candidates = set()
    for base_prefix in {pathlib.Path(sys.base_prefix), pathlib.Path(sys.prefix)}:
        lib_dir = base_prefix / "lib"
        if lib_dir.exists():
            lib_candidates.add(lib_dir)

    framework_prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
    py_short_version = sysconfig.get_config_var("py_version_short")
    if framework_prefix and py_short_version:
        framework_dir = pathlib.Path(framework_prefix)
        lib_dir = framework_dir / "Versions" / py_short_version / "lib"
        if lib_dir.exists():
            lib_candidates.add(lib_dir)

    dylib_names = ["libtcl8.7.dylib", "libtcl8.6.dylib", "libtk8.7.dylib", "libtk8.6.dylib"]

    seen_binaries = set()
    for lib_dir in lib_candidates:
        for name in dylib_names:
            candidate = lib_dir / name
            if candidate.exists():
                key = str(candidate.resolve())
                if key not in seen_binaries:
                    binaries.append((str(candidate), name))
                    seen_binaries.add(key)

    # Fallback to ctypes util discovery in case the dylibs live elsewhere.
    for lookup in ("tcl8.7", "tcl8.6", "tk8.7", "tk8.6"):
        try:
            path = ctypes.util.find_library(lookup)
        except Exception:
            path = None
        if not path:
            continue
        candidate = pathlib.Path(path)
        if candidate.exists():
            key = str(candidate.resolve())
            if key not in seen_binaries:
                binaries.append((str(candidate), candidate.name))
                seen_binaries.add(key)

version_file = None
if sys.platform.startswith("win"):
    candidate_version = PROJECT_DIR / "version.txt"
    if candidate_version.exists():
        version_file = str(candidate_version)

a = Analysis(
    ["launcher.py"],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(PROJECT_DIR / "talks_reducer" / "pyinstaller_hooks" / "tkinter_env.py"),
    ] if sys.platform == "darwin" else [],
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

    if icon_file:
        info_plist["CFBundleIconFile"] = pathlib.Path(icon_file).stem

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
