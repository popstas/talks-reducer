#!/bin/bash

# Build script for talks-reducer GUI using PyInstaller
# Supports Windows, macOS, and Linux

set -e

echo "🔨 Building talks-reducer GUI with PyInstaller..."

# Detect OS
OS_TYPE=$(uname -s)
case "$OS_TYPE" in
    Darwin*)
        OS_NAME="macos"
        echo "📱 Detected macOS"
        export MACOSX_DEPLOYMENT_TARGET=10.13
        ;;
    Linux*)
        OS_NAME="linux"
        echo "🐧  Detected Linux"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        OS_NAME="windows"
        echo "🪟  Detected Windows"
        ;;
    *)
        OS_NAME="unknown"
        echo "⚠️  Unknown OS: $OS_TYPE"
        ;;
esac

# Ensure we're in the project root
cd "$(dirname "$0")/.."

# Determine the current project version (used for artifact naming)
VERSION=""
if command -v python3 &> /dev/null; then
    VERSION=$(python3 - <<'PY' 2>/dev/null || true)
import pathlib
import re

path = pathlib.Path("pyproject.toml")
version = ""
if path.exists():
    match = re.search(r"^version\s*=\s*\"([^\"]+)\"", path.read_text(), re.MULTILINE)
    if match:
        version = match.group(1).strip()

print(version)
PY
    )
    VERSION=${VERSION//$'\r'/}
    VERSION=${VERSION//$'\n'/}
fi

# Check if pyinstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "❌ PyInstaller not found. Installing..."
    pip install pyinstaller
fi

# Clean previous builds (keep build/ for incremental builds unless --clean flag)
if [[ "$1" == "--clean" ]]; then
    echo "🧹 Full clean build..."
    rm -rf build dist/*.spec 2>/dev/null || echo "⚠️  Some files couldn't be cleaned (may be in use), continuing..."
else
    echo "🔄 Incremental build (use --clean for full rebuild)..."
    rm -f dist/*.spec 2>/dev/null || true
fi

# Build the GUI executable
echo "⚙️  Running PyInstaller..."

# Exclude unnecessary heavy dependencies (but keep numpy/scipy as they're required)
EXCLUDES="--exclude-module PySide6 \
--exclude-module PyQt5 \
--exclude-module PyQt6 \
--exclude-module pandas \
--exclude-module matplotlib \
--exclude-module numba \
--exclude-module cupy"

# First, generate the spec file
if [[ "$OS_NAME" == "windows" ]]; then
    pyinstaller launcher.py --name talks-reducer --windowed \
        --hidden-import=tkinterdnd2 \
        --collect-submodules talks_reducer \
        --icon=docs/assets/icon.ico \
        --version-file=version.txt \
        $EXCLUDES \
        --noconfirm \
        --workpath build \
        --distpath dist
else
    PYINSTALLER_ARGS=(launcher.py --name talks-reducer --windowed \
        --hidden-import=tkinterdnd2 \
        --collect-submodules talks_reducer \
        --icon=docs/assets/icon.ico \
        $EXCLUDES \
        --noconfirm)

    if [[ "$OS_NAME" == "macos" ]]; then
        mkdir -p "dist/talks-reducer.app"
        # Produce the most compatible binary we can. Prefer universal builds
        # when the Python runtime and dependencies contain both arm64 and
        # x86_64 slices, otherwise fall back to the active architecture to
        # avoid PyInstaller attempting to thin non-fat binaries.
        if command -v pyinstaller &> /dev/null && pyinstaller --help 2>/dev/null | grep -q -- "--target-arch"; then
            TARGET_ARCH=""
            HOST_ARCH=$(uname -m)
            HOST_TARGET=""
            case "$HOST_ARCH" in
                arm64|aarch64)
                    HOST_TARGET="arm64"
                    ;;
                x86_64|amd64)
                    HOST_TARGET="x86_64"
                    ;;
            esac

            if command -v python3 &> /dev/null; then
                PYTHON_SHARED_LIB=$(python3 - <<'PY'
import sysconfig
libname = sysconfig.get_config_var('LDLIBRARY') or ''
libdir = sysconfig.get_config_var('LIBDIR') or ''
if libname and libdir:
    import os
    path = os.path.join(libdir, libname)
    if os.path.exists(path):
        print(path)
PY
)
            fi

            if [[ -n "$PYTHON_SHARED_LIB" && -f "$PYTHON_SHARED_LIB" ]] && command -v lipo &> /dev/null; then
                LIPO_INFO=$(lipo -info "$PYTHON_SHARED_LIB" 2>/dev/null || true)
                if echo "$LIPO_INFO" | grep -q "Architectures in the fat file"; then
                    TARGET_ARCH="universal2"
                elif echo "$LIPO_INFO" | grep -q "Non-fat file"; then
                    TARGET_ARCH="$HOST_TARGET"
                fi
            fi

            if [[ -z "$TARGET_ARCH" ]]; then
                TARGET_ARCH="$HOST_TARGET"
            fi

            if [[ -z "$TARGET_ARCH" ]]; then
                TARGET_ARCH="universal2"
            fi

            echo "🎯 macOS build target architecture: $TARGET_ARCH"
            PYINSTALLER_ARGS+=(--target-arch "$TARGET_ARCH")
        else
            echo "⚠️  This version of PyInstaller does not support --target-arch;"
            echo "   falling back to the default architecture."
        fi
    fi

    pyinstaller "${PYINSTALLER_ARGS[@]}"
fi

# Find the output directory (PyInstaller may use dist/ or dist/)
if [[ -d "dist/talks-reducer.app" ]]; then
    OUTPUT_DIR="dist/talks-reducer.app"
elif [[ -d "dist/talks-reducer" ]]; then
    OUTPUT_DIR="dist/talks-reducer"
else
    OUTPUT_DIR=""
fi

# Remove CUDA DLLs (not needed, saves ~500MB)
if [[ -n "$OUTPUT_DIR" && -d "$OUTPUT_DIR/_internal" ]]; then
    echo "🧹 Removing unnecessary CUDA libraries..."
    rm -f "$OUTPUT_DIR/_internal"/cublas*.dll \
          "$OUTPUT_DIR/_internal"/cufft*.dll \
          "$OUTPUT_DIR/_internal"/curand*.dll \
          "$OUTPUT_DIR/_internal"/cusolver*.dll \
          "$OUTPUT_DIR/_internal"/cusparse*.dll \
          "$OUTPUT_DIR/_internal"/cudnn*.dll \
          "$OUTPUT_DIR/_internal"/nvcuda*.dll \
          "$OUTPUT_DIR/_internal"/nvrtc*.dll \
          "$OUTPUT_DIR/_internal"/cuTENSOR*.dll 2>/dev/null
    echo "✅ Removed CUDA libraries"
fi

# macos sign
if [[ "$OS_NAME" == "macos" ]]; then
  if [[ "${SIGN_MACOS_APP:-0}" == "1" ]]; then
    APP="dist/talks-reducer.app"
    IDENTITY="${CODESIGN_IDENTITY:-Developer ID Application: Stanislav Popov ()}"

    # Check if the signing identity exists in the keychain
    if ! security find-identity -v -p codesigning | grep -q "$IDENTITY" 2>/dev/null; then
        echo "⚠️  Signing identity not found in keychain: $IDENTITY"
        echo "⚠️  Skipping code signing. Set SIGN_MACOS_APP=0 to suppress this warning."
    else
        # Create entitlements if missing
        [[ -f entitlements.plist ]] || cat > entitlements.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.files.user-selected.read-write</key><true/>
</dict></plist>
PLIST

        echo "🔐 Signing nested binaries…"
        find "$APP/Contents" \( -name "*.dylib" -o -name "*.so" -o -perm +111 -type f \) -print0 \
        | xargs -0 -I{} codesign --force --options runtime \
            --entitlements entitlements.plist --timestamp -s "$IDENTITY" "{}"

        echo "🔐 Signing app bundle…"
        codesign --force --deep --options runtime --entitlements entitlements.plist \
            --timestamp -s "$IDENTITY" "$APP"

        echo "🧪 Verifying signature…"
        codesign --verify --deep --strict --verbose=2 "$APP" || exit 1

        echo "📨 Submitting for notarization…"
        # assumes notarytool profile already set up
        xcrun notarytool submit "$APP" --keychain-profile talks-notary --wait || exit 1

        echo "📎 Stapling ticket…"
        xcrun stapler staple "$APP" || exit 1

        echo "✅ Gatekeeper check:"
        spctl -a -vv --type execute "$APP"
    fi
  else
    echo "⚠️  Skipping macOS code signing (SIGN_MACOS_APP is not set to 1)."
  fi
fi


# Prepare target directory
echo "📦 Preparing artifacts..."
mkdir -p dist

if [[ "$OS_NAME" == "macos" ]]; then
    if [[ "$OUTPUT_DIR" == *.app ]]; then
        TARGET="dist/talks-reducer.app"
    else
        TARGET="dist/talks-reducer-macos-universal"
    fi
elif [[ "$OS_NAME" == "windows" ]]; then
    TARGET="dist/talks-reducer-windows"
elif [[ "$OS_NAME" == "linux" ]]; then
    TARGET="dist/talks-reducer-linux"
else
    TARGET="dist/talks-reducer"
fi

# Move output to target
if [[ -n "$OUTPUT_DIR" && -d "$OUTPUT_DIR" ]]; then
    # Check if output is already at target location
    if [[ "$OUTPUT_DIR" == "$TARGET" ]]; then
        echo "✅ Build complete: $TARGET/"
    else
        # Remove old target if it exists
        if [[ -d "$TARGET" ]]; then
            rm -rf "$TARGET" 2>/dev/null || {
                echo "⚠️  Could not remove $TARGET (may be in use)"
                exit 1
            }
        fi
        
        # Move to target
        if mv "$OUTPUT_DIR" "$TARGET" 2>/dev/null; then
            echo "✅ Build complete: $TARGET/"
        else
            echo "⚠️  Could not move from $OUTPUT_DIR to $TARGET"
            echo "✅ Build output at: $OUTPUT_DIR/"
        fi
    fi

    if [[ "$OS_NAME" == "macos" ]]; then
        # Codesign the bundle if credentials are provided. This keeps Gatekeeper
        # from flagging the app as modified during transport and is required
        # before notarization.
        if [[ -n "$MACOS_CODESIGN_IDENTITY" ]]; then
            APP_BUNDLE="$TARGET"
            if [[ -d "$APP_BUNDLE" && "$APP_BUNDLE" != *.app ]]; then
                FIRST_APP=$(find "$APP_BUNDLE" -maxdepth 1 -name "*.app" -print -quit)
                if [[ -n "$FIRST_APP" ]]; then
                    APP_BUNDLE="$FIRST_APP"
                fi
            fi

            if [[ -d "$APP_BUNDLE" ]]; then
                echo "🔏 Codesigning $APP_BUNDLE with identity '$MACOS_CODESIGN_IDENTITY'..."
                SIGN_CMD=(codesign --force --deep --options runtime --sign "$MACOS_CODESIGN_IDENTITY")
                if [[ -n "$MACOS_CODESIGN_ENTITLEMENTS" ]]; then
                    SIGN_CMD+=(--entitlements "$MACOS_CODESIGN_ENTITLEMENTS")
                fi
                if "${SIGN_CMD[@]}" "$APP_BUNDLE"; then
                    echo "✅ Codesigning succeeded"
                else
                    echo "⚠️  Codesigning failed"
                fi
            fi
        fi

        # Notarize using xcrun notarytool if a keychain profile is available.
        if [[ -n "$MACOS_NOTARIZE_PROFILE" ]]; then
            if ! command -v xcrun &> /dev/null; then
                echo "⚠️  Cannot notarize: xcrun not found"
            else
                APP_BUNDLE="$TARGET"
                if [[ -d "$APP_BUNDLE" && "$APP_BUNDLE" != *.app ]]; then
                    FIRST_APP=$(find "$APP_BUNDLE" -maxdepth 1 -name "*.app" -print -quit)
                    if [[ -n "$FIRST_APP" ]]; then
                        APP_BUNDLE="$FIRST_APP"
                    fi
                fi

                if [[ -d "$APP_BUNDLE" ]]; then
                    ARCHIVE_PATH="${APP_BUNDLE%.app}.zip"
                    echo "📦 Creating notarization archive at $ARCHIVE_PATH..."
                    /usr/bin/ditto -c -k --keepParent "$APP_BUNDLE" "$ARCHIVE_PATH"
                    echo "📮 Submitting bundle for notarization using profile '$MACOS_NOTARIZE_PROFILE'..."
                    if xcrun notarytool submit "$ARCHIVE_PATH" --keychain-profile "$MACOS_NOTARIZE_PROFILE" --wait; then
                        echo "✅ Notarization succeeded; stapling ticket..."
                        if xcrun stapler staple "$APP_BUNDLE"; then
                            echo "✅ Stapled notarization ticket"
                        else
                            echo "⚠️  Stapling failed"
                        fi
                    else
                        echo "⚠️  Notarization failed"
                    fi
                fi
            fi
        fi
    fi

    # Clean up dist if empty
    [[ -d "dist" ]] && rmdir dist 2>/dev/null || true
else
    echo "⚠️  Build output not found"
fi

echo ""
echo "🎉 GUI build successful!"
echo "📂 Output directory: dist/"

# Create zip if --zip flag is provided
if [[ "$*" == *"--zip"* ]]; then
    echo ""
    echo "📦 Creating zip archive..."
    
    if [[ -d "$TARGET" ]]; then
        cd dist
        TARGET_NAME=$(basename "$TARGET")
        ZIP_NAME="$TARGET_NAME"

        if [[ "$OS_NAME" == "windows" && -n "$VERSION" ]]; then
            ZIP_NAME="${TARGET_NAME}-${VERSION}"
        fi

        if [[ "$OS_NAME" == "windows" ]]; then
            powershell Compress-Archive -Path "$TARGET_NAME" -DestinationPath "${ZIP_NAME}.zip" -Force
        else
            zip -r "${ZIP_NAME}.zip" "$TARGET_NAME"
        fi

        if [[ -f "${ZIP_NAME}.zip" ]]; then
            echo "✅ Created: dist/${ZIP_NAME}.zip"
            ls -lh "${ZIP_NAME}.zip"
        fi
        cd ..
    fi
fi
