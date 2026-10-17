#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Static check of an IngeTrazo extension: does it actually register anything?

This is the failure ``dev/check.sh`` alone does not catch. A file that parses
perfectly but defines no ``Tool`` subclass and no ``setup(app)`` loads without
error and does **nothing** — the Extensions menu simply stays empty, with
nothing in the log to explain it.

Also enforces this project's conventions (SPDX header, a docstring, a
lowercase file stem), because the community catalog's robot checks the same
ground before it will list an extension.

Usage:  python3 dev/lint.py [path ...]      (default: extensions/)
Exit code 1 when any file fails.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

STEM_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _looks_like_tool(node: ast.ClassDef) -> bool:
    """True when the class inherits from something named ``*Tool``.

    Matched by name: the plugin is imported with ``core.*``/``tools.*``
    importable, but this check runs outside the app and must not import them.
    """
    return any(isinstance(base, ast.Name) and base.id.endswith("Tool")
               or isinstance(base, ast.Attribute) and base.attr.endswith("Tool")
               for base in node.bases)


def check(path: Path) -> list[str]:
    problems: list[str] = []
    stem = path.stem if path.is_file() else path.name

    if path.is_file():
        if not STEM_RE.match(stem):
            problems.append(f"name {stem!r}: use lowercase letters, digits and _")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))       # SyntaxError -> caller
        first = source.splitlines()[0] if source.splitlines() else ""
        if "SPDX-License-Identifier" not in first:
            problems.append("first line is not an SPDX-License-Identifier header")
        if ast.get_docstring(tree, clean=False) is None:
            problems.append("no module docstring (say what it does and which "
                            "IngeTrazo version it was tested with)")
    else:
        source = ""
        tree = None

    modules = [path] if path.is_file() else sorted(p for p in path.glob("*.py")
                                                   if not p.name.startswith("_"))
    tools, setups = [], []
    for module in modules:
        tree = tree if path.is_file() and module is path else ast.parse(
            module.read_text(encoding="utf-8"), filename=str(module))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and _looks_like_tool(node):
                tools.append(node.name)
            elif isinstance(node, ast.FunctionDef) and node.name == "setup":
                args = node.args.args
                if len(args) != 1:
                    problems.append("setup() must take exactly the app argument")
                else:
                    setups.append(node.name)

    if not tools and not setups:
        problems.append("registers nothing: no Tool subclass and no setup(app) "
                        "defined in the file")
    else:
        parts = []
        if tools:
            parts.append("tools: " + ", ".join(tools))
        if setups:
            parts.append("setup(app)")
        print(f"     {' | '.join(parts)}")
    return problems


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    targets = [Path(a) for a in argv[1:]] or [root / "extensions"]

    failures = 0
    for target in targets:
        if not target.exists():
            print(f"no such path: {target}", file=sys.stderr)
            failures += 1
            continue
        entries = [target] if target.is_file() else [
            p for p in sorted(target.iterdir())
            if (p.is_file() and p.suffix == ".py" and not p.name.startswith("_"))
            or (p.is_dir() and not p.name.startswith("_")
                and (p / "__init__.py").is_file())]
        if not entries:
            print(f"nothing to check in {target}")
        for entry in entries:
            print(f"  {entry.name}")
            try:
                problems = check(entry)
            except SyntaxError as exc:
                print(f"     syntax error: {exc}")
                failures += 1
                continue
            for problem in problems:
                print(f"     !! {problem}")
            failures += bool(problems)

    if failures:
        print(f"{failures} extension(s) failed the contract check.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
