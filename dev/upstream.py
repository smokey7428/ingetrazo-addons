#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""What upstream could give us, and whether a release has brought it yet.

Run this after installing a new IngeTrazo. It reports the installed version, the
version this project was last tested against, and — from the *source* clone in
`reference/` — whether each feature we are waiting for has landed, and whether
the two things we depend on privately are still there.

It cannot read the installed app: the bundle is PyInstaller-compiled, so `core/`
and `views/` are not importable from outside. The source clone is the stand-in,
which is why it refreshes it first.

Exit code is 1 when something we *depend on* has moved, so this can be the first
thing you run before blaming our code.

Usage:  ./dev/upstream.sh          (or: python3 dev/upstream.py [--offline])
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "reference" / "ingetrazo"
APP = Path("/Applications/IngeTrazo.app")
#: The IngeTrazo version the extensions in this repository were last tested
#: against, and the one the catalog entries claim.
TESTED = "0.5.9"

#: ``(what, why it matters to us, file, pattern)`` — pattern present = landed.
WANTED = (
    ("A public way to register an interactive tool",
     "would replace the private reach in openings/host.py — the one thing the "
     "catalog reviewer flagged",
     "views/extension_api.py", r"def (add_tool|register_tool)\b"),
    ("Exporter / importer registration",
     "our .ifc writer could hook into File ▸ Export instead of replacing it",
     "views/extension_api.py", r"def (add_exporter|add_importer)\b"),
    ("A host/opening API in the core",
     "walls and openings could stop being an extension's own model — upstream "
     "ROADMAP item 1",
     "core/bim.py", r"def (host|opening|void)\w*"),
    ("IfcOpeningElement in the core's export",
     "our walls' openings would export without our writer",
     "formats/ifc.py", r"IFCOPENINGELEMENT|IfcOpeningElement"),
    ("IFC2X3 writing in the core",
     "the schema we still have to add ourselves",
     "formats/ifc.py", r"IFC2X3"),
    ("Booleans offered to extensions",
     "the wall generator could subtract openings instead of assembling blocks",
     "core/solids.py", r"^def run\b"),
)

#: What we depend on privately. A change here breaks our tools, not our panels.
DEPENDED = (
    ("MainWindow._tools", "views/main_window.py", r"self\._tools\b"),
    ("MainWindow._activate_tool", "views/main_window.py",
     r"def _activate_tool\b"),
    ("MainWindow._tool_actions", "views/main_window.py", r"self\._tool_actions\b"),
    ("MainWindow._tool_group", "views/main_window.py", r"self\._tool_group\b"),
    ("Viewport.pick_face", "views/viewport.py", r"def pick_face\b"),
    ("Viewport.pick_face_any", "views/viewport.py", r"def pick_face_any\b"),
    ("Viewport._world_under_cursor", "views/viewport.py",
     r"def _world_under_cursor\b"),
    ("group.ext (a group's own parameters)", "core/group.py", r"\.ext\b"),
    ("scene.plugin_data", "core/scene.py", r"plugin_data"),
    ("SnapshotImport", "core/history.py", r"class SnapshotImport\b"),
)


def installed_version() -> str:
    """The version in the app bundle, without launching it."""
    plist = APP / "Contents" / "Info.plist"
    if not plist.is_file():
        return "not installed"
    try:
        out = subprocess.run(["plutil", "-extract", "CFBundleShortVersionString",
                              "raw", str(plist)],
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def refresh_source(offline: bool) -> str:
    """Bring the source clone up to date, and say how far it moved."""
    if not (SOURCE / ".git").exists():
        return "no source clone in reference/ — see AGENTS.md"
    if offline:
        return "not refreshed (--offline)"
    try:
        subprocess.run(["git", "-C", str(SOURCE), "fetch", "--depth", "1",
                        "origin"], capture_output=True, timeout=120)
        head = subprocess.run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        remote = subprocess.run(["git", "-C", str(SOURCE), "rev-parse",
                                 "FETCH_HEAD"], capture_output=True, text=True,
                                timeout=30)
        if head.stdout.strip() == remote.stdout.strip():
            return "up to date"
        subprocess.run(["git", "-C", str(SOURCE), "checkout", "-q",
                        "FETCH_HEAD"], capture_output=True, timeout=60)
        return f"updated to {remote.stdout.strip()[:8] or 'a new commit'}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not refresh ({type(exc).__name__})"


def look(path: str, pattern: str) -> tuple[bool, str]:
    """Whether ``pattern`` is in ``path``'s current text, with the first line."""
    target = SOURCE / path
    if not target.is_file():
        return False, "file missing"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, str(exc)
    found = re.search(pattern, text, re.MULTILINE)
    if found is None:
        return False, ""
    line = text[:found.start()].count("\n") + 1
    return True, f"{path}:{line}"


def source_version() -> str:
    """The version in the source clone, from its own ``core/version.py``."""
    path = SOURCE / "core" / "version.py"
    if not path.is_file():
        return "unknown"
    found = re.search(r"__version__\s*=\s*[\"']([^\"']+)",
                      path.read_text(encoding="utf-8", errors="replace"))
    return found.group(1) if found else "unknown"


def main(argv: list[str]) -> int:
    offline = "--offline" in argv
    installed = installed_version()
    print(f"IngeTrazo installed : {installed}")
    print(f"Last tested against : {TESTED}")
    print(f"Source clone        : {source_version()}")
    print(f"Clone refresh       : {refresh_source(offline)}")
    print(f"Source clone now    : {source_version()}")
    if installed not in (TESTED, "unknown", "not installed"):
        print()
        print(f"  Note: the installed app is {installed}, and the catalog entries "
              f"claim {TESTED}.")
        print("  Either install that release, or re-test and change TESTED in "
              "this script.")
    print()

    print("What would help us:")
    for what, why, path, pattern in WANTED:
        here, where = look(path, pattern)
        mark = "HERE " if here else "  —  "
        print(f"  {mark} {what}")
        print(f"        {why}")
        if here:
            print(f"        {where}")
    print()

    print("What we depend on (a change here breaks our tools, not our panels):")
    moved = []
    for what, path, pattern in DEPENDED:
        here, where = look(path, pattern)
        print(f"  {'ok   ' if here else 'GONE '} {what}"
              + (f"  ({where})" if here else ""))
        if not here:
            moved.append(what)
    print()

    if moved:
        print(f"{len(moved)} dependency/dependencies have moved. Check "
              f"openings/host.py first: it is the one module that reaches into "
              f"the application, and it is meant to be the only one.")
        return 1
    print("Nothing we depend on has moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
