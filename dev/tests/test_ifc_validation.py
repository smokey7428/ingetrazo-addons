#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Validate the exported IFC4 against a REAL consumer: ifcopenshell.

`test_ifc_writer.py` checks the file with this project's own STEP reader. That
proves the structure we intended; it cannot prove that an independent IFC
implementation accepts it. This does — the same bar the core's own
`tests/test_ifc_validation.py` holds `formats/ifc.py` to.

**ifcopenshell is a dev-only dependency** (deliberately not in requirements.txt
and not in the app bundle). The whole file skips when it is absent, so the suite
stays green on a machine without it. To run it:

    T="${TMPDIR:-/tmp}/opencode/ifcos"
    python3 -m pip install --target "$T" --no-deps ifcopenshell==0.9.0.post1
    PYTHONPATH="$T" python3 dev/tests/test_ifc_validation.py

Usage:  python3 dev/tests/test_ifc_validation.py
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app_stubs                                                    # noqa: E402

ROOT = HERE.parent.parent
IFC = ROOT / "extensions" / "ifc_editor"
OPENINGS = ROOT / "extensions" / "openings"

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


def close(got, want, message: str, tol: float = 1e-3) -> None:
    check(abs(got - want) <= tol,
          f"{message}: got {got!r}, want {want!r}")


def load(package: str, base: Path, name: str):
    full = f"{package}.{name}"
    spec = importlib.util.spec_from_file_location(full, base / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    setattr(sys.modules[package], name, module)
    spec.loader.exec_module(module)
    return module


def install_package(name: str, folder: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package


def build(path: Path, schema: str = "IFC4", dropped: list | None = None,
          wall_type: str = "STANDARD") -> None:
    """A wall of ours with a window hosted in it, and fields the core drops."""
    app_stubs.install()
    install_package("ingetrazo_plugin_openings", OPENINGS)
    for name in ("profiles", "params", "geometry", "walls", "wall_geometry",
                 "opening", "object", "wall_object", "hosting"):
        load("ingetrazo_plugin_openings", OPENINGS, name)
    install_package("ingetrazo_plugin_ifc_editor", IFC)
    load("ingetrazo_plugin_ifc_editor", IFC, "schema")
    store = load("ingetrazo_plugin_ifc_editor", IFC, "store")
    writer = load("ingetrazo_plugin_ifc_editor", IFC, "writer")

    walls = sys.modules["ingetrazo_plugin_openings.walls"]
    wall_object = sys.modules["ingetrazo_plugin_openings.wall_object"]
    hosting = sys.modules["ingetrazo_plugin_openings.hosting"]

    scene = app_stubs.Scene()
    viewport = app_stubs.Viewport(scene)
    V = app_stubs.QVector3D
    w = walls.normalize({"height": 2.7, "path": [[0, 0], [4, 0]]})
    wall = wall_object.create(scene, w)
    # A predefined type on the wall: IFC4 keeps it on the wall, IFC2X3 on an
    # IfcWallType, and both have to work.
    store.edit(viewport, store.object_key(wall),
               fields={"Description": "Dragende wand",
                       "PredefinedType": wall_type})
    window = hosting.add(scene, wall, V(2.0, 0.05, 1.2), V(0, 1, 0),
                         {"kind": "window", "type": "swing"})
    store.edit(viewport, store.object_key(window),
               fields={"Description": "Draairaam 1.0 x 1.5",
                       "ObjectType": "HR++",
                       "PredefinedType": "WINDOW",
                       "PartitioningType": "SINGLE_PANEL"},
               psets={"Pset_WindowCommon": {"IsExternal": True,
                                            "Reference": "R-01"}})
    writer.save(scene, path, "Validation", schema, dropped=dropped)


def schema_messages(model) -> list:
    """What ifcopenshell's own validator says about the file."""
    import ifcopenshell.validate

    messages: list = []

    class _Collect(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger = logging.getLogger("ifc_validation")
    logger.handlers[:] = [_Collect()]
    logger.setLevel(logging.DEBUG)
    ifcopenshell.validate.validate(model, logger)
    return messages


def main() -> int:
    try:
        import ifcopenshell
        import ifcopenshell.geom
        import ifcopenshell.util.element
        import ifcopenshell.validate
    except ImportError:
        print("ifc_validation: skipped (ifcopenshell is not installed — see "
              "the docstring for the one command that installs it)")
        return 0

    path = HERE / "_validation.ifc"
    build(path)
    model = ifcopenshell.open(str(path))
    equal(model.schema, "IFC4", "ifcopenshell reads it as IFC4")

    # ---- schema validation against an independent implementation ----
    messages = schema_messages(model)
    check(not messages,
          f"no schema validation messages, got {len(messages)}: "
          f"{messages[:3]}")

    # ---- what we wrote is what it reads ----
    walls = model.by_type("IfcWall")
    equal(len(walls), 1, "the wall is there")
    equal(walls[0].Name, "Wall 01", "with its name")

    windows = model.by_type("IfcWindow")
    equal(len(windows), 1, "and the window")
    equal(windows[0].Description, "Draairaam 1.0 x 1.5",
          "with the description the core would have dropped")
    equal(windows[0].ObjectType, "HR++", "and its ObjectType")
    equal(str(windows[0].PredefinedType), "WINDOW", "and PredefinedType")
    equal(str(windows[0].PartitioningType), "SINGLE_PANEL",
          "and its partitioning, from the enum the schema names for it")

    # The property sets, read back with ifcopenshell's own reader.
    props = ifcopenshell.util.element.get_psets(windows[0])
    common = props.get("Pset_WindowCommon") or {}
    equal(common.get("IsExternal"), True, "IsExternal came back True")
    equal(common.get("Reference"), "R-01", "and Reference as text")

    # ---- a hole is an opening, not a gap ----
    voids = model.by_type("IfcRelVoidsElement")
    fills = model.by_type("IfcRelFillsElement")
    equal(len(voids), 1, "the wall has one voiding relation")
    equal(len(fills), 1, "and the window fills it")
    equal(voids[0].RelatingBuildingElement.id(), walls[0].id(),
          "the void belongs to the wall")
    equal(fills[0].RelatingOpeningElement.id(),
          voids[0].RelatedOpeningElement.id(),
          "and the fill belongs to that void")

    # ---- the geometry survives an independent tessellator ----
    settings = ifcopenshell.geom.settings()
    seen = {}
    for product in model.by_type("IfcProduct"):
        if product.Representation is None:
            continue
        shape = ifcopenshell.geom.create_shape(settings, product)
        seen[product.is_a()] = len(shape.geometry.verts) // 3
    for name in ("IfcWall", "IfcWindow", "IfcOpeningElement"):
        check(seen.get(name, 0) > 0, f"{name} tessellates ({seen.get(name, 0)} "
                                     f"vertices)")

    # The opening is the size we asked for: 1.0 x 1.5 through a 300 mm wall.
    opening = model.by_type("IfcOpeningElement")[0]
    shape = ifcopenshell.geom.create_shape(settings, opening)
    verts = shape.geometry.verts
    xs, ys, zs = verts[0::3], verts[1::3], verts[2::3]
    close(max(xs) - min(xs), 1.0, "the opening is 1.0 m along the wall")
    close(max(zs) - min(zs), 1.5, "1.5 m high")
    close(max(ys) - min(ys), 0.3, "and runs through the 300 mm wall")

    equal(str(walls[0].PredefinedType), "STANDARD",
          "the wall's predefined type, on the wall in IFC4")

    # ---- the same document as IFC2X3 ----
    # The layout is the tables' business; the *vocabulary* is not. A layered
    # wall is IfcWallStandardCase, and the predefined type has to travel to an
    # IfcWallType and back through an IfcRelDefinesByType — or it does not
    # travel at all.
    older = HERE / "_validation_2x3.ifc"
    dropped: list = []
    build(older, "IFC2X3", dropped)
    old = ifcopenshell.open(str(older))
    equal(old.schema, "IFC2X3", "ifcopenshell reads it as IFC2X3")
    said = schema_messages(old)
    check(not said, f"no IFC2X3 schema messages, got {len(said)}: {said[:3]}")

    equal(len([wall for wall in old.by_type("IfcWall")
               if wall.is_a() == "IfcWall"]), 0,
          "a layered wall is not written as a plain IfcWall")
    standard = old.by_type("IfcWallStandardCase")
    equal(len(standard), 1, "but as an IfcWallStandardCase")
    equal(standard[0].Name, "Wall 01", "with its name")
    equal(standard[0].Description, "Dragende wand",
          "and the description the core would have dropped")

    kinds = old.by_type("IfcWallType")
    equal(len(kinds), 1, "the predefined type became one IfcWallType")
    equal(str(kinds[0].PredefinedType), "STANDARD", "carrying the value")
    links = old.by_type("IfcRelDefinesByType")
    equal(len(links), 1, "linked back to the wall")
    equal(links[0].RelatingType.id(), kinds[0].id(),
          "through the type relation")
    equal([o.id() for o in links[0].RelatedObjects], [standard[0].id()],
          "and to that wall")

    # IFC2X3 has nowhere to put a window's PredefinedType — IfcWindowStyle has
    # no such attribute — so the export must say so rather than lose it.
    equal(len(old.by_type("IfcWindow")), 1, "the window is there")
    check(any("PredefinedType" in note and "window" in note.lower()
              for note in dropped),
          f"and its dropped predefined type is reported: {dropped}")

    # The hole is still a hole, and still the size we asked for.
    equal(len(old.by_type("IfcRelVoidsElement")), 1,
          "the wall is voided in IFC2X3 too")
    equal(len(old.by_type("IfcRelFillsElement")), 1, "and the window fills it")
    settings = ifcopenshell.geom.settings()
    shape = ifcopenshell.geom.create_shape(
        settings, old.by_type("IfcOpeningElement")[0])
    verts = shape.geometry.verts
    xs, zs = verts[0::3], verts[2::3]
    close(max(xs) - min(xs), 1.0, "the opening is still 1.0 m along the wall")
    close(max(zs) - min(zs), 1.5, "and still 1.5 m high")
    # A value this schema's enumeration does not have is refused *and* said out
    # loud. SOLIDWALL is an IFC4 wall type; IFC2X3 has no such literal, and a
    # field that vanishes quietly is the thing this writer exists to prevent.
    strict = HERE / "_validation_strict.ifc"
    said_again: list = []
    build(strict, "IFC2X3", said_again, wall_type="SOLIDWALL")
    checked = ifcopenshell.open(str(strict))
    equal(len(checked.by_type("IfcWallType")), 0,
          "SOLIDWALL is not an IFC2X3 wall type, so no type object is written")
    check(any("SOLIDWALL" in note for note in said_again),
          f"and the export reports it: {said_again}")
    strict.unlink()

    older.unlink()

    path.unlink()
    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"ifc validation: ok ({checks} checks, against ifcopenshell)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
