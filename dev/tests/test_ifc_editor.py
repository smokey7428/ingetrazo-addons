#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Test the ifc_editor extension's logic without IngeTrazo.

Why the core is stubbed: ``store.py`` imports ``core.group``, ``core.history``
and ``core.mesh``, all of which need PySide6 and the application around them.
A handful of tiny stand-ins are enough to exercise everything worth testing
here — identity, resolution, the merge with the core's BIM tag, and that one
edit is exactly one undoable step that restores both storages.

What this cannot tell you is whether the panel draws. That is a restart of
IngeTrazo: install, open the IFC panel, select a tagged wall.

Usage:  python3 dev/tests/test_ifc_editor.py
"""
from __future__ import annotations

import abc
import importlib.util
import json
import sys
import types
from pathlib import Path

EXT = (Path(__file__).resolve().parent.parent.parent
       / "extensions" / "ifc_editor")

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


# ---- the core, stubbed ------------------------------------------------------
def install_core_stubs() -> None:
    core = types.ModuleType("core")
    core.__path__ = []                               # a package, for submodules
    sys.modules["core"] = core

    mesh = types.ModuleType("core.mesh")

    class Face:
        def __init__(self, ifc=None):
            self.attrs = {} if ifc is None else {"ifc": dict(ifc)}

    class Edge:
        pass

    mesh.Face, mesh.Edge = Face, Edge
    sys.modules["core.mesh"] = mesh

    group = types.ModuleType("core.group")

    class Group:
        def __init__(self, name="Group", uid="uid0001", ifc=None):
            self.name, self.uid, self.ifc = name, uid, ifc

    group.Group = Group
    sys.modules["core.group"] = group

    history = types.ModuleType("core.history")

    class Command(abc.ABC):
        @abc.abstractmethod
        def do(self, scene):
            """apply"""

        @abc.abstractmethod
        def undo(self, scene):
            """reverse"""

    history.Command = Command
    sys.modules["core.history"] = history

    bim = types.ModuleType("core.bim")

    def collect_objects(scene):
        out = []
        by_id: dict = {}
        for face in scene.loose_mesh.faces:
            tag = face.attrs.get("ifc")
            if tag:
                by_id.setdefault(tag.get("id"), []).append(face)
        for obj_id, faces in by_id.items():
            out.append({"key": ("faces", obj_id), "class": faces[0].attrs["ifc"]
                        .get("class", ""), "faces": faces})
        for g in scene.groups:
            if getattr(g, "ifc", None):
                out.append({"key": ("group", id(g)), "group": g,
                            "class": (g.ifc or {}).get("class", "")})
        return out

    bim.collect_objects = collect_objects
    sys.modules["core.bim"] = bim


class Scene:
    """Just enough scene: plugin_data, version, groups, loose faces."""

    def __init__(self):
        self.plugin_data: dict = {}
        self.version = 0
        self.groups: list = []
        self.loose_mesh = types.SimpleNamespace(faces=[])


def load(name: str):
    """Import a module of the extension by path, the way IngeTrazo would."""
    path = EXT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ingetrazo_plugin_test_{name}",
                                                  path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---- the schema tables ------------------------------------------------------
def test_schema(schema, store, Group, Face) -> None:
    ifc4 = schema.load("IFC4")
    ifc2x3 = schema.load("IFC2X3")

    equal(ifc4.schema, "IFC4", "IFC4 table identity")
    equal(ifc2x3.schema, "IFC2X3", "IFC2X3 table identity")
    check(len(ifc4.entities) == 776, f"IFC4 entities: {len(ifc4.entities)}")
    check(len(ifc2x3.entities) == 653,
          f"IFC2X3 entities: {len(ifc2x3.entities)}")
    check(bool(ifc4.attribution), "the table carries buildingSMART attribution")
    check("buildingSMART" in ifc4.attribution,
          "the attribution should name buildingSMART")

    # Attributes come back in the order IFC writes them, inherited first.
    equal([a["name"] for a in ifc4.attributes("IfcWall")],
          ["GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
           "ObjectPlacement", "Representation", "Tag", "PredefinedType"],
          "IFC4 IfcWall attribute order")
    equal(ifc4.attributes("IfcWall")[0].get("inherited_from"), "IfcRoot",
          "GlobalId is declared on IfcRoot")
    check(ifc2x3.predefined_types("IfcWall") == [],
          "IFC2X3 IfcWall has no predefined type")
    check("STANDARD" in ifc4.predefined_types("IfcWall"),
          "IFC4 IfcWall offers STANDARD")

    # Inheritance, which is what makes the applicable property sets work.
    check(ifc2x3.is_subtype_of("IfcWallStandardCase", "IfcWall"),
          "IfcWallStandardCase is an IfcWall in IFC2X3")
    check(ifc4.is_subtype_of("IfcWall", "IfcProduct"),
          "an IfcWall is a product")
    check(not ifc4.is_subtype_of("IfcProject", "IfcProduct"),
          "IfcProject is not a product")

    # The class picker: concrete products only, and plenty of them.
    products = ifc4.product_names()
    check(len(products) > 120, f"IFC4 product classes: {len(products)}")
    check("IfcWall" in products and "IfcCurtainWall" in products,
          "the picker should reach past the core's 16 curated classes")
    check(not any(ifc4.entities[n].get("abstract") for n in products),
          "an abstract entity must not be offered as a class")

    # Values decide which editor a field gets.
    equal(ifc4.resolve_kind("IfcLabel"), "string", "IfcLabel is text")
    equal(ifc4.resolve_kind("IfcBoolean"), "boolean", "IfcBoolean is a flag")
    equal(ifc4.resolve_kind("IfcLengthMeasure"), "real",
          "IfcLengthMeasure is a number")
    equal(ifc4.resolve_kind("IfcPositiveInteger"), "integer",
          "IfcPositiveInteger follows its alias to integer")
    equal(ifc4.resolve_kind("IfcWallTypeEnum"), "enum", "an enum is an enum")
    equal(ifc4.resolve_kind("IfcMaterial"), "entity",
          "IfcMaterial is an entity, not a value type")
    equal(ifc4.resolve_kind("IfcShell"), "select", "IfcShell is a select")

    # Applicable property sets, including the two quirks of the published data.
    wall_sets = dict(ifc4.psets_for("IfcWall"))
    check("Pset_WallCommon" in wall_sets, "Pset_WallCommon applies to IfcWall")
    check("Qto_WallBaseQuantities" in wall_sets,
          "the quantity set applies too")
    check("Qto_WallBaseQuantities" in wall_sets
          and wall_sets["Qto_WallBaseQuantities"]["kind"] == "qto",
          "and is marked as a quantity set")
    wall_common = wall_sets["Pset_WallCommon"]
    check(any(p["name"] == "IsExternal" for p in wall_common["properties"]),
          "Pset_WallCommon offers IsExternal")

    # IFC2X3 names both wall entities in one set; a subtype inherits it.
    check("Pset_WallCommon" in dict(ifc2x3.psets_for("IfcWallStandardCase")),
          "IFC2X3 Pset_WallCommon reaches IfcWallStandardCase")

    # Pset_CoveringFlooring is only for coverings whose type is FLOORING.
    equal([n for n, _e in ifc4.psets_for("IfcCovering", None)
           if n == "Pset_CoveringFlooring"], [],
          "Pset_CoveringFlooring is withheld without the predefined type")
    check("Pset_CoveringFlooring" in
          [n for n, _e in ifc4.psets_for("IfcCovering", "FLOORING")],
          "and offered with it — including the enum's own spelling")

    # Nothing should be offered twice, or for the wrong class entirely.
    names = [n for n, _e in ifc4.psets_for("IfcWall")]
    equal(len(names), len(set(names)), "no property set offered twice")
    check("Pset_DoorCommon" not in names,
          "a door's set must not apply to a wall")


# ---- identity, storage and undo ---------------------------------------------
def test_store(schema, store, Group, Face) -> None:
    scene = Scene()

    # Identity: a group by uid, loose faces by their BIM tag id.
    group = Group(name="Wall A", uid="abc123", ifc={"class": "IfcWall",
                                                    "name": "Wall A"})
    tagged = Face({"id": 7, "class": "IfcWall", "name": "W1"})
    untagged = Face()
    scene.groups.append(group)
    scene.loose_mesh.faces.extend([tagged, untagged])

    equal(store.object_key(group), "uid:abc123", "a group keys on its uid")
    equal(store.object_key(tagged), "ifc:7", "faces key on the tag id")
    equal(store.object_key(untagged), None, "untagged geometry has no key")
    equal(store.object_key("something else"), None, "nor has a non-entity")

    equal(store.resolve(scene, "uid:abc123"), ([], [group]), "resolve a group")
    equal(store.resolve(scene, "ifc:7"), ([tagged], []), "resolve faces")

    # A record merges the core's tag with what we store.
    entry = store.record(scene, group)
    equal(entry["class"], "IfcWall", "the class comes from the core tag")
    equal(entry["name"], "Wall A", "the name too")
    equal(entry["schema"], "IFC4", "the default schema is IFC4")
    equal(entry["fields"], {}, "and we hold nothing yet")

    # One edit, one undo step, both storages.
    store.edit(_Viewport(scene), "uid:abc123",
               fields={"Description": "load-bearing",
                       "ObjectType": "shear wall",
                       "Tag": "W-01"},
               psets={"Pset_WallCommon": {"IsExternal": True,
                                          "LoadBearing": True}},
               schema="IFC2X3")
    entry = store.record(scene, group)
    equal(entry["fields"]["Description"], "load-bearing", "the field is stored")
    equal(entry["psets"]["Pset_WallCommon"]["LoadBearing"], True,
          "the property set is stored")
    equal(entry["schema"], "IFC2X3", "the schema choice is stored")
    equal(scene.version, 1, "one edit bumps the version once")

    # Changing the class writes through to the core's own tag.
    store.edit(_Viewport(scene), "uid:abc123", ifc_class="IfcCurtainWall",
               name="Curtain wall A")
    equal(group.ifc["class"], "IfcCurtainWall",
          "the core tag follows the class")
    equal(group.ifc["name"], "Curtain wall A",
          "and the name, so the BIM panel agrees")

    # A second object keeps its own fields.
    store.edit(_Viewport(scene), "ifc:7", fields={"Tag": "W-02"})
    equal(store.record(scene, tagged)["fields"]["Tag"], "W-02",
          "the second object is stored separately")
    equal(store.record(scene, group)["fields"]["Tag"], "W-01",
          "and did not disturb the first")

    # Undo must put BOTH storages back exactly.
    before = json.dumps(scene.plugin_data, sort_keys=True)
    tag_before = dict(group.ifc)
    viewport = _Viewport(scene)
    store.edit(viewport, "uid:abc123", ifc_class="IfcSlab",
               fields={"Tag": "MISTAKE"})
    equal(group.ifc["class"], "IfcSlab", "the change landed")
    viewport.history.undo()
    equal(json.dumps(scene.plugin_data, sort_keys=True), before,
          "undo restores the plugin data byte for byte")
    equal(group.ifc, tag_before, "and the core tag as it was")

    # Undo of a tag change that ADDED the key removes it again — the mesh
    # snapshot does not cover group tags, so the command has to.
    fresh = Group(name="P", uid="newuid")
    scene.groups.append(fresh)
    viewport = _Viewport(scene)
    store.edit(viewport, "uid:newuid", ifc_class="IfcColumn",
               fields={"Tag": "C-1"})
    check(store.stored(scene, "uid:newuid"), "the new entry is there")
    viewport.history.undo()
    equal(store.stored(scene, "uid:newuid"), {},
          "undo removes the entry it created")


class _History:
    def __init__(self):
        self.undo_stack: list = []

    def execute(self, command) -> None:
        command.do(self._scene)
        self.undo_stack.append(command)

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.undo_stack.pop().undo(self._scene)
        return True


class _Viewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = _History()
        self.history._scene = scene
        self.updates = 0

    def update(self) -> None:
        self.updates += 1

    def notify_scene_changed(self) -> None:
        self.updates += 1


def main() -> int:
    install_core_stubs()
    schema = load("schema")
    store = load("store")
    Group = sys.modules["core.group"].Group
    Face = sys.modules["core.mesh"].Face

    test_schema(schema, store, Group, Face)
    test_store(schema, store, Group, Face)

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"ifc_editor: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
