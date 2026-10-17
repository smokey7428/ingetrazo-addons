#!/usr/bin/env bash
#
# Check every extension before restarting IngeTrazo:
#   1. byte-compile it, so a syntax error is caught here rather than as a
#      disabled "⚠ (load error)" entry in the Extensions menu;
#   2. dev/lint.py, which catches the failure compilation cannot — a file that
#      parses but registers no Tool subclass and no setup(app), so it loads and
#      does nothing at all.
#
# Neither check runs the code: a typo in a core attribute name still only shows
# up when the app runs.
#
# Usage: ./dev/check.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

shopt -s nullglob
failed=0
checked=0

for path in "$ROOT"/extensions/*.py "$ROOT"/extensions/*/; do
  case "$path" in
    */_*) continue ;;
  esac
  if [ -d "$path" ]; then
    [ -f "${path}__init__.py" ] || continue
  fi
  checked=$((checked + 1))
  if "$PY" -m py_compile "$path"; then
    echo "  ok   $(basename "$path")"
  else
    failed=$((failed + 1))
  fi
done

find "$ROOT/extensions" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

if [ "$failed" -gt 0 ]; then
  echo "$failed of $checked extension(s) failed to compile." >&2
  exit 1
fi
echo "$checked extension(s) compile."

echo
echo "contract:"
"$PY" "$ROOT/dev/lint.py" "$@"

# The schema tables an extension ships are generated artefacts — check they
# are present and still self-consistent. Skipped when no extension has any.
if compgen -G "$ROOT/extensions/*/data/*.json.gz" > /dev/null; then
  echo
  echo "schema tables:"
  "$PY" "$ROOT/dev/schema/test_tables.py"
fi
