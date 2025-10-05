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
    pyinstaller launcher.py --name talks-reducer --windowed \
        --hidden-import=tkinterdnd2 \
        --collect-submodules talks_reducer \
        --icon=docs/assets/icon.ico \
        $EXCLUDES \
        --noconfirm
fi

# Find the output directory (PyInstaller may use dist/ or dist/)
if [[ -d "dist/talks-reducer" ]]; then
    OUTPUT_DIR="dist/talks-reducer"
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

# Prepare target directory
echo "📦 Preparing artifacts..."
mkdir -p dist

if [[ "$OS_NAME" == "macos" ]]; then
    TARGET="dist/talks-reducer-macos-universal"
elif [[ "$OS_NAME" == "windows" ]]; then
    TARGET="dist/talks-reducer-windows"
elif [[ "$OS_NAME" == "linux" ]]; then
    TARGET="dist/talks-reducer-linux"
else
    TARGET="dist/talks-reducer"
fi

# Move output to target
if [[ -n "$OUTPUT_DIR" && -d "$OUTPUT_DIR" ]]; then
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
        echo "⚠️  Could not move to $TARGET"
        echo "✅ Build output at: $OUTPUT_DIR/"
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
        
        if [[ "$OS_NAME" == "windows" ]]; then
            powershell Compress-Archive -Path "$TARGET_NAME" -DestinationPath "${TARGET_NAME}.zip" -Force
        else
            zip -r "${TARGET_NAME}.zip" "$TARGET_NAME"
        fi
        
        if [[ -f "${TARGET_NAME}.zip" ]]; then
            echo "✅ Created: dist/${TARGET_NAME}.zip"
            ls -lh "${TARGET_NAME}.zip"
        fi
        cd ..
    fi
fi
