#!/usr/bin/env bash
# generate_icons.sh — generate app.icns, app.ico, app-256.png from a single PNG
# Platform: macOS
# Deps: ImageMagick (magick or convert), iconutil
# Usage:
#   chmod +x generate_icons.sh
#   ./generate_icons.sh
# Options:
#   -s, --src    source PNG (default: talks_reducer/resources/icons/icon.png)
#   -d, --dest   destination dir (default: talks_reducer/resources/icons)
#   -f, --force  overwrite outputs if exist
#   -h, --help   show help

set -euo pipefail

log() { printf "[icons] %s\n" "$*"; }
err() { printf "[icons][ERROR] %s\n" "$*" >&2; exit 1; }
has_cmd() { command -v "$1" >/dev/null 2>&1; }

pick_im() {
  if has_cmd magick; then echo "magick"; return 0; fi
  if has_cmd convert; then echo "convert"; return 0; fi
  return 1
}

usage() {
  sed -n '1,40p' "$0" | sed 's/^# \{0,1\}//'
}

# Defaults relative to project root (script is executed from project root)
SRC="talks_reducer/resources/icons/icon.png"
DEST="talks_reducer/resources/icons"
FORCE=0

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--src)  SRC="$2"; shift 2 ;;
    -d|--dest) DEST="$2"; shift 2 ;;
    -f|--force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "Unknown arg: $1" ;;
  esac
done

# Normalize to absolute paths without changing directory
if [[ "$SRC" != /* ]]; then SRC="$(pwd)/$SRC"; fi
if [[ "$DEST" != /* ]]; then DEST="$(pwd)/$DEST"; fi

ICONSET_DIR="$DEST/app.iconset"
ICNS_PATH="$DEST/app.icns"
ICO_PATH="$DEST/app.ico"
PNG256_PATH="$DEST/app-256.png"

IM_BIN="$(pick_im || true)"
[[ -n "$IM_BIN" ]] || err "ImageMagick not found. Install via: brew install imagemagick"
has_cmd iconutil || err "iconutil not found. Install Xcode CLT: xcode-select --install"

[[ -f "$SRC" ]] || err "Source PNG not found: $SRC"
mkdir -p "$DEST"

log "Source: $SRC"
log "Dest:   $DEST"

maybe_skip() {
  local path="$1"
  if [[ -f "$path" && $FORCE -eq 0 ]]; then
    log "Exists, skipping (use --force to overwrite): $path"
    return 0
  fi
  return 1
}

# PNG 256
if ! maybe_skip "$PNG256_PATH"; then
  log "Generating PNG 256x256 → $PNG256_PATH"
  "$IM_BIN" "$SRC" -resize 256x256 "$PNG256_PATH"
fi

# ICO (Windows)
if ! maybe_skip "$ICO_PATH"; then
  log "Generating ICO (256,128,64,48,32,24,16) → $ICO_PATH"
  if [[ "$IM_BIN" == "magick" ]]; then
    "$IM_BIN" "$SRC" -define icon:auto-resize=256,128,64,48,32,24,16 "$ICO_PATH"
  else
    TMP_DIR="$(mktemp -d)"; trap 'rm -rf "$TMP_DIR"' EXIT
    for s in 256 128 64 48 32 24 16; do
      "$IM_BIN" "$SRC" -resize ${s}x${s} "$TMP_DIR/icon_${s}.png"
    done
    "$IM_BIN" "$TMP_DIR/icon_256.png" "$TMP_DIR/icon_128.png" "$TMP_DIR/icon_64.png" \
              "$TMP_DIR/icon_48.png"  "$TMP_DIR/icon_32.png"  "$TMP_DIR/icon_24.png" \
              "$TMP_DIR/icon_16.png" "$ICO_PATH"
  fi
fi

# ICNS (macOS)
if ! maybe_skip "$ICNS_PATH"; then
  log "Preparing iconset → $ICONSET_DIR"
  rm -rf "$ICONSET_DIR"; mkdir -p "$ICONSET_DIR"
  for s in 16 32 64 128 256 512 1024; do
    "$IM_BIN" "$SRC" -resize ${s}x${s} "$ICONSET_DIR/icon_${s}x${s}.png"
    DOUBLE=$((s*2))
    "$IM_BIN" "$SRC" -resize ${DOUBLE}x${DOUBLE} "$ICONSET_DIR/icon_${s}x${s}@2x.png"
  done
  log "Building ICNS → $ICNS_PATH"
  iconutil -c icns "$ICONSET_DIR" -o "$ICNS_PATH"
  rm -rf "$ICONSET_DIR"
fi

log "Done. Outputs:"
[[ -f "$ICNS_PATH"  ]] && echo " - $ICNS_PATH"
[[ -f "$ICO_PATH"   ]] && echo " - $ICO_PATH"
[[ -f "$PNG256_PATH" ]] && echo " - $PNG256_PATH"

log "Use with PyInstaller:"
echo "  macOS:   --icon talks_reducer/resources/icons/app.icns"
echo "  Windows: --icon talks_reducer/resources/icons/app.ico"
echo "  Tk/Tray: talks_reducer/resources/icons/app-256.png"

