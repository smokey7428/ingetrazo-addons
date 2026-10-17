#!/usr/bin/env bash
#
# Symlink every extension in extensions/ into IngeTrazo's per-user plugins
# folder, so what we edit here is what the app loads. No copy to keep in sync.
#
# IngeTrazo scans its plugin folders ONLY at startup: a symlinked file takes
# effect the next time the app is opened.
#
# Usage: ./dev/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/extensions"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/ingetrazo/plugins"

if [ ! -d "$SRC" ]; then
  echo "no extensions/ directory at $SRC" >&2
  exit 1
fi

mkdir -p "$DEST"

link() {  # link <source path> <name in the plugin folder>
  local source="$1" name="$2" target="$DEST/$2"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "  !! skipped $name — a real file/folder is installed there" >&2
    echo "     (not ours: remove or rename it by hand first)" >&2
    return 1
  fi
  ln -sfn "$source" "$target"
  echo "  -> $name"
}

echo "extensions/ -> $DEST"
count=0
shopt -s nullglob

for path in "$SRC"/*.py; do
  name="$(basename "$path")"
  [[ "$name" == _* ]] && continue          # _private helpers are not plugins
  link "$path" "$name" && count=$((count + 1))
done

for path in "$SRC"/*/; do
  name="$(basename "$path")"
  [[ "$name" == _* ]] && continue
  [ -f "${path}__init__.py" ] || continue  # only packages are plugins
  link "${path%/}" "$name" && count=$((count + 1))
done

echo "$count extension(s) linked. Restart IngeTrazo to load them."
