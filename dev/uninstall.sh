#!/usr/bin/env bash
#
# Remove only the symlinks that point into THIS project's extensions/ folder.
# Extensions installed from the catalog (a real file or folder) are left alone.
#
# Usage: ./dev/uninstall.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/extensions"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/ingetrazo/plugins"

[ -d "$DEST" ] || { echo "nothing installed at $DEST"; exit 0; }

echo "checking $DEST"
removed=0
for target in "$DEST"/*; do
  [ -L "$target" ] || continue
  link="$(readlink "$target")"
  case "$link" in
    "$SRC"/*) rm "$target"; echo "  <- $(basename "$target")"; removed=$((removed + 1)) ;;
  esac
done

echo "$removed symlink(s) removed. Restart IngeTrazo to unload them."
