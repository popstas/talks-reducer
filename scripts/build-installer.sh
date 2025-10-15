#!/usr/bin/env bash
set -euo pipefail

# Build the Windows installer by invoking Inno Setup with the repository's
# recipe. Requires that the PyInstaller GUI bundle has already been generated
# in dist/talks-reducer/ (for example via scripts/build-gui.sh).

# Ensure we are in the project root
cd "$(dirname "$0")/.."

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

read_version() {
  "$PYTHON_BIN" scripts/get-version.py
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

APP_PUBLISHER=${APP_PUBLISHER:-Talks Reducer}

ISCC_BIN=${ISCC_BIN:-iscc}
if ! command -v "$ISCC_BIN" >/dev/null 2>&1; then
  FALLBACK_PATHS=(
    "/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
    "/c/Program Files/Inno Setup 6/ISCC.exe"
  )
  for candidate in "${FALLBACK_PATHS[@]}"; do
    if [[ -x "$candidate" ]]; then
      ISCC_BIN="$candidate"
      break
    fi
  done
fi

if ! command -v "$ISCC_BIN" >/dev/null 2>&1 && [[ ! -x "$ISCC_BIN" ]]; then
  echo "Inno Setup compiler (iscc) is not available. Install Inno Setup before running this script." >&2
  exit 1
fi

# Convert paths to Windows form when running under MSYS/MinGW shells so that
# Inno Setup receives the expected backslash paths.
normalize_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path"
  else
    printf '%s' "$path"
  fi
}

ISS_SCRIPT="scripts/talks-reducer-installer.iss"
if [[ ! -f "$ISS_SCRIPT" ]]; then
  echo "Installer script $ISS_SCRIPT missing" >&2
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
WIN_OUTPUT_DIR=$(normalize_path "$PWD")

OUTPUT_BASENAME="talks-reducer-${APP_VERSION}-setup.exe"

"$ISCC_BIN" \
  "/DAPP_VERSION=$APP_VERSION" \
  "/DSOURCE_DIR=$WIN_SOURCE_DIR" \
  "/DAPP_ICON=$WIN_APP_ICON" \
  "/DAPP_PUBLISHER=$APP_PUBLISHER" \
  "/DOUTPUT_DIR=$WIN_OUTPUT_DIR" \
  "$ISS_SCRIPT"

if [[ ! -f "$OUTPUT_BASENAME" ]]; then
  echo "Expected Inno Setup to produce $OUTPUT_BASENAME" >&2
  exit 1
fi

mkdir -p dist
mv "$OUTPUT_BASENAME" "dist/$OUTPUT_BASENAME"

echo "✅ Created dist/$OUTPUT_BASENAME"

