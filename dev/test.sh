#!/usr/bin/env bash
#
# Run the tests. They stub the core (and Qt) so they run without IngeTrazo,
# without PySide6 and without the extension being installed.
#
# What they cover: the schema tables, the extension's identity and storage
# rules, and the panel's logic — building the form for a tagged element,
# filling it from the schema, committing an edit as one undo step, and undoing
# it. What they cannot: whether anything looks right, or whether a Qt enum or
# signal is used correctly. That needs a restart of IngeTrazo.
#
# Usage: ./dev/test.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"

failed=0
shopt -s nullglob
for test in "$ROOT"/dev/schema/test_*.py "$ROOT"/dev/tests/test_*.py; do
  echo "== $(basename "$test")"
  if ! "$PY" "$test"; then
    failed=$((failed + 1))
  fi
done

find "$ROOT/dev" "$ROOT/extensions" -name '__pycache__' -type d \
  -exec rm -rf {} + 2>/dev/null || true

if [ "$failed" -gt 0 ]; then
  echo "$failed test file(s) failed." >&2
  exit 1
fi
echo "all tests pass."
