#!/usr/bin/env bash
set -euo pipefail

# Build the Windows installer by invoking NSIS with the repository's recipe.
# Requires that the PyInstaller GUI bundle has already been generated in
# dist/talks-reducer/ (for example via scripts/build-gui.sh).

# Ensure we are in the project root
cd "$(dirname "$0")/.."

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

read_version() {
  "$PYTHON_BIN" - <<'PY'
import importlib.util
import pathlib

about_path = pathlib.Path("talks_reducer/__about__.py")
if about_path.exists():
    spec = importlib.util.spec_from_file_location("talks_reducer.__about__", about_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = getattr(module, "__version__", "")
    if version:
        print(version)
        raise SystemExit

pyproject = pathlib.Path("pyproject.toml")
if pyproject.exists():
    for line in pyproject.read_text().splitlines():
        if line.strip().startswith("version") and "=" in line:
            print(line.split("=", 1)[1].strip().strip('"'))
            raise SystemExit
print("")
PY
}

APP_VERSION=${APP_VERSION:-$(read_version)}
if [[ -z "$APP_VERSION" ]]; then
  echo "Unable to determine package version. Set APP_VERSION explicitly." >&2
  exit 1
fi

SOURCE_DIR=${SOURCE_DIR:-dist/talks-reducer}
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "PyInstaller output not found at $SOURCE_DIR. Run scripts/build-gui.sh first." >&2
  exit 1
fi

if ! command -v makensis >/dev/null 2>&1; then
  echo "makensis is not available. Install NSIS before running this script." >&2
  exit 1
fi

# Convert paths to Windows form when running under MSYS/MinGW shells so that
# NSIS receives the expected backslash paths.
normalize_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path"
  else
    printf '%s' "$path"
  fi
}

NSI_SCRIPT="scripts/talks-reducer-installer.nsi"
if [[ ! -f "$NSI_SCRIPT" ]]; then
  echo "Installer script $NSI_SCRIPT missing" >&2
  exit 1
fi

APP_ICON_DEFAULT="talks_reducer/resources/icons/app.ico"
APP_ICON=${APP_ICON:-$APP_ICON_DEFAULT}
if [[ ! -f "$APP_ICON" ]]; then
  echo "Icon not found at $APP_ICON" >&2
  exit 1
fi

WIN_SOURCE_DIR=$(normalize_path "$SOURCE_DIR")
WIN_APP_ICON=$(normalize_path "$APP_ICON")

OUTPUT_BASENAME="talks-reducer-${APP_VERSION}-setup.exe"

makensis \
  "/DAPP_VERSION=$APP_VERSION" \
  "/DSOURCE_DIR=$WIN_SOURCE_DIR" \
  "/DAPP_ICON=$WIN_APP_ICON" \
  "$NSI_SCRIPT"

if [[ ! -f "$OUTPUT_BASENAME" ]]; then
  echo "Expected NSIS to produce $OUTPUT_BASENAME" >&2
  exit 1
fi

mkdir -p dist
mv "$OUTPUT_BASENAME" "dist/$OUTPUT_BASENAME"

echo "✅ Created dist/$OUTPUT_BASENAME"

