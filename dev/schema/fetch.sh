#!/usr/bin/env bash
#
# Fetch the third-party sources the schema tables are generated from.
#
# These are NOT part of this project and are not committed: they are large,
# they are somebody else's copyright, and the generator reduces them to the
# compact tables we do ship. Re-running this is only needed to move to a newer
# schema revision.
#
#   IFC4.exp / IFC2X3_TC1.exp   buildingSMART International — the EXPRESS
#                               schemas: every entity, attribute, type and
#                               enumeration. (Their licence permits use in
#                               software development with full attribution;
#                               see dev/schema/README.md.)
#   Pset_*.ifc                  buildingSMART's property-set definitions, as
#                               distributed with IfcOpenShell — 513 set
#                               templates for IFC4, 317 for IFC2X3, each with
#                               its applicable entity.
#
# Usage: ./dev/schema/fetch.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/src"
mkdir -p "$SRC"

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "\
"(KHTML, like Gecko) Chrome/120 Safari/537.36"

# standards.buildingsmart.org serves the EXPRESS files only to a browser-like
# user agent; without one it answers 403.
get() {  # get <url> <destination>
  echo "  $(basename "$2")"
  curl -sSL --max-time 180 -A "$UA" -o "$2" "$1"
  [ -s "$2" ] || { echo "    !! empty, fetch failed" >&2; return 1; }
}

echo "buildingSMART EXPRESS schemas:"
get "https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/EXPRESS/IFC4.exp" \
    "$SRC/IFC4.exp"
get "https://standards.buildingsmart.org/IFC/RELEASE/IFC2x3/TC1/EXPRESS/IFC2X3_TC1.exp" \
    "$SRC/IFC2X3_TC1.exp"

# Pinned to a commit, never a branch: what we generate has to be reproducible.
IOS_COMMIT="2fae1dea0db318c8d0a72e2cd956a9b8c0d7fd0e"
IOS_PATH="src/ifcopenshell-python/ifcopenshell/util/schema"
echo "buildingSMART property-set definitions (IfcOpenShell @ ${IOS_COMMIT:0:8}):"
get "https://raw.githubusercontent.com/IfcOpenShell/IfcOpenShell/$IOS_COMMIT/$IOS_PATH/Pset_IFC4_ADD2.ifc" \
    "$SRC/Pset_IFC4_ADD2.ifc"
get "https://raw.githubusercontent.com/IfcOpenShell/IfcOpenShell/$IOS_COMMIT/$IOS_PATH/Pset_IFC2X3.ifc" \
    "$SRC/Pset_IFC2X3.ifc"

echo
ls -la "$SRC"
echo "now run: python3 dev/schema/generate.py"
