#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Check the IFC writer: write a file, then read it back with our own reader.

Two things are tested, and they are the two that matter:

* **the file is structurally sound** — every instance parses, every reference
  points at an instance that exists, and the entity names are the ones IFC uses.
  ``dev/schema/spf.py`` is this project's own STEP reader, so the writer is
  checked by code that did not write it.
* **the fields you edited are in it** — including the ones the core's writer
  throws away (Description, ObjectType, PredefinedType, every Pset), and an
  opening in a wall is an ``IfcOpeningElement`` with its relations, not a hole.

The bar this cannot reach here is a *real* consumer: ifcopenshell is not
installed on this machine, so schema validation against an independent
implementation still has to happen where it is available.

Usage:  python3 dev/tests/test_ifc_writer.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app_stubs                                                    # noqa: E402

ROOT = HERE.parent.parent
IFC = ROOT / "extensions" / "ifc_editor"
OPENINGS = ROOT / "extensions" / "openings"

# our own STEP reader, from the schema generator — the writer is checked by
# code that did not write it
sys.path.insert(0, str(ROOT / "dev" / "schema"))
import spf                                                          # noqa: E402

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


def close(got, want, message: str, tol: float = 1e-4) -> None:
    check(abs(got - want) <= tol,
          f"{message}: got {got!r}, want {want!r}")


# ---- load the two extensions the way IngeTrazo would ------------------------
def load(package: str, base: Path, name: str, path: Path | None = None):
    full = f"{package}.{name}"
    spec = importlib.util.spec_from_file_location(full, path or base / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    setattr(sys.modules[package], name, module)
    spec.loader.exec_module(module)
    return module


def install_package(name: str, folder: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package


def main() -> int:
    app_stubs.install()
    install_package("ingetrazo_plugin_openings", OPENINGS)
    walls = load("ingetrazo_plugin_openings", OPENINGS, "walls")
    wall_geometry = load("ingetrazo_plugin_openings", OPENINGS, "wall_geometry")
    load("ingetrazo_plugin_openings", OPENINGS, "geometry")
    load("ingetrazo_plugin_openings", OPENINGS, "params")
    load("ingetrazo_plugin_openings", OPENINGS, "profiles")
    load("ingetrazo_plugin_openings", OPENINGS, "opening")
    object_mod = load("ingetrazo_plugin_openings", OPENINGS, "object")
    wall_object = load("ingetrazo_plugin_openings", OPENINGS, "wall_object")
    hosting = load("ingetrazo_plugin_openings", OPENINGS, "hosting")

    install_package("ingetrazo_plugin_ifc_editor", IFC)
    load("ingetrazo_plugin_ifc_editor", IFC, "schema")
    store = load("ingetrazo_plugin_ifc_editor", IFC, "store")
    writer = load("ingetrazo_plugin_ifc_editor", IFC, "writer")

    scene = app_stubs.Scene()
    viewport = app_stubs.Viewport(scene)
    V = app_stubs.QVector3D

    # A wall of ours with a window hosted in it.
    w = walls.normalize({"type": "binnenwand", "height": 2.7,
                         "path": [[0, 0], [4, 0]]})
    wall = wall_object.create(scene, w)
    window = hosting.add(scene, wall, V(2.0, 0.05, 1.2), V(0, 1, 0),
                         {"kind": "window", "type": "swing"})

    # Give the window the fields the core's writer would drop.
    store.edit(viewport, store.object_key(window),
               fields={"Description": "Draairaam, 1.0 × 1.5",
                       "ObjectType": "HR++",
                       "PredefinedType": "WINDOW",
                       "PartitioningType": "SINGLE_PANEL"},
               psets={"Pset_WindowCommon": {"IsExternal": True,
                                            "Reference": "R-01"}})

    path = ROOT / "dev" / "tests" / "_writer_test.ifc"
    count = writer.save(scene, path, "Writer test", "IFC4")
    text = path.read_text(encoding="utf-8")
    instances = spf.parse(text)

    equal(spf.header_schema(text), "IFC4", "the header names the schema")
    equal(count, 2, "both tagged objects were written — the wall and window")
    check(bool(instances), "and the file parses as a STEP file")

    kinds = {i.type_name for i in instances.values()}
    for needed in ("IFCWALL", "IFCOPENINGELEMENT", "IFCRELVOIDSELEMENT",
                   "IFCRELFILLSELEMENT", "IFCPROPERTYSET", "IFCFACETEDBREP"):
        check(needed in kinds, f"the file has a {needed}")

    # Every reference points at something that exists.
    missing = []
    for eid, instance in instances.items():
        for arg in instance.args:
            for ref in _refs(arg):
                if ref.id not in instances:
                    missing.append((eid, ref.id))
    check(not missing, f"every reference resolves (first: {missing[:3]})")

    # The wall's own attributes, in the schema's order.
    walls_out = [i for i in instances.values() if i.type_name == "IFCWALL"]
    equal(len(walls_out), 1, "one IfcWall")
    wall_attrs = walls_out[0].args
    equal(len(wall_attrs), 9,
          "IfcWall carries its nine attributes, from the schema")
    equal(wall_attrs[2], "Wall 01", "the name is the group's")

    # The window's edited fields — the ones the core writes as $.
    windows = [i for i in instances.values() if i.type_name == "IFCWINDOW"]
    equal(len(windows), 1, "the window is in the file too")
    attributes = windows[0].args
    equal(attributes[3], "Draairaam, 1.0 × 1.5", "its Description survived")
    equal(attributes[4], "HR++", "and its ObjectType")
    check("WINDOW" in str(attributes), "and its PredefinedType")
    check("SINGLE_PANEL" in str(attributes),
          "and its partitioning, from a legal enumeration")
    # (IfcWindow has no OperationType — that is a door's attribute — so what
    # matters is that the schema's own list decided the layout.)
    equal(len(attributes), 13, f"IfcWindow carries its thirteen: {attributes}")

    # The opening's properties, which exist only because we wrote them.
    names = [str(i.get(0)) for i in instances.values()
             if i.type_name == "IFCPROPERTYSINGLEVALUE"]
    check("IsExternal" in names, f"Pset values were written: {names}")
    check("Reference" in names, "both of them")

    # The opening voids the wall and the window fills the opening.
    voids = [i for i in instances.values() if i.type_name == "IFCRELVOIDSELEMENT"]
    equal(len(voids), 1, "one IfcRelVoidsElement")
    equal(voids[0].args[4].id, _id_of(instances, "IFCWALL"),
          "and it voids the wall")
    fills = [i for i in instances.values() if i.type_name == "IFCRELFILLSELEMENT"]
    equal(len(fills), 1, "one IfcRelFillsElement")
    equal(fills[0].args[4].id, _id_of(instances, "IFCOPENINGELEMENT"),
          "and the window fills the opening")

    path.unlink()
    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"ifc writer: ok ({checks} checks)")
    return 0


def _refs(arg):
    if isinstance(arg, spf.Ref):
        return [arg]
    if isinstance(arg, tuple):
        out = []
        for item in arg:
            out.extend(_refs(item))
        return out
    return []


def _id_of(instances, type_name) -> int:
    for eid, instance in instances.items():
        if instance.type_name == type_name:
            return eid
    return -1


if __name__ == "__main__":
    raise SystemExit(main())
