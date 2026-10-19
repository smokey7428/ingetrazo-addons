#!/usr/bin/env bash
#
# What has upstream given us since we last looked? Run this after installing a
# new IngeTrazo — it reports the version, refreshes the source clone, and lists
# the features we are waiting for plus the private members we depend on.
#
# Usage: ./dev/upstream.sh [--offline]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON:-python3}" "$ROOT/dev/upstream.py" "$@"
