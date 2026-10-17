#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Check that a door really cuts a wall, and that the wall comes back.

This is the integration test for the two riskiest things in the extension:

* **the wall around an opening is still a closed solid** — every edge of the
  loose mesh borders exactly two faces. Cutting a face out and not adding the
  reveals, or adding a reveal wound the wrong way, breaks that, and the wall
  would silently lose its volume in the take-off;
* **one action is one undo step**, and undo puts back the mesh, the groups,
  the plugin data, the materials *and* the layers.

Usage:  python3 dev/tests/test_openings_object.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app_stubs                                                    # noqa: E402

EXT = HERE.parent.parent / "extensions" / "openings"

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


def close(got, want, message: str, tol: float = 1e-6) -> None:
    check(abs(got - want) <= tol,
          f"{message}: got {got!r}, want {want!r}")


def load(name: str):
    full = f"ingetrazo_plugin_openings.{name}"
    spec = importlib.util.spec_from_file_location(full, EXT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    setattr(sys.modules["ingetrazo_plugin_openings"], name, module)
    spec.loader.exec_module(module)
    return module


def install_package() -> None:
    import types
    package = types.ModuleType("ingetrazo_plugin_openings")
    package.__path__ = [str(EXT)]
    sys.modules["ingetrazo_plugin_openings"] = package


# ---- a wall to cut into -----------------------------------------------------
def box(scene, x0, y0, z0, x1, y1, z1, attrs=None):
    """A closed box, wound outward — six faces, four corners each. The real
    app draws these with the Rectangle tool and Push/Pull; here we only need
    the result."""
    V = app_stubs.QVector3D
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    made = []
    for a, b, cc, d in quads:
        face = scene.mesh.add_face([V(*c[a]), V(*c[b]), V(*c[cc]), V(*c[d])])
        face.attrs = dict(attrs or {"layer": "Walls"})
        made.append(face)
    return made


def front_face(scene, y_value: float):
    """The wall face the user would click: at ``y_value``, facing -y."""
    for face in scene.mesh.faces:
        n = face.normal().normalized()
        if (abs(n.y() + 1.0) < 1e-6
                and all(abs(v.position.y() - y_value) < 1e-6
                        for v in face.loop)):
            return face
    raise AssertionError("no front face found")


def setup(scene, wall=(0.0, 0.0, 0.0, 4.0, 0.30, 2.70)):
    """A wall on the Walls layer, with the layer declared."""
    scene.layers.append(app_stubs.Layer("Walls"))
    return box(scene, *wall, attrs={"layer": "Walls", "mat": "Brick"})


# ---- the tests --------------------------------------------------------------
def test_axes() -> None:
    scene = app_stubs.Scene()
    setup(scene)
    face = front_face(scene, 0.0)                 # faces -y, the user's side
    across, into, up = opening_mod.axes(face)
    close(into.y(), 1.0, "into a wall facing -y is +y")
    close(up.z(), 1.0, "and up is up")
    close(across.x(), 1.0, "across runs towards the viewer's right (+x here)")
    # Right-handed: X cross Y is Z.
    cross = app_stubs.QVector3D.crossProduct(across, into)
    close(cross.z(), 1.0, "the frame is right-handed")

    # And on the wall's other side the frame flips, as it must: a door on the
    # back of a wall is drawn from the other side of it.
    back = [f for f in scene.mesh.faces
            if abs(f.normal().normalized().y() - 1.0) < 1e-6][0]
    across2, into2, _up2 = opening_mod.axes(back)
    close(into2.y(), -1.0, "into the back face is -y")
    close(across2.x(), -1.0, "and the viewer's right is -x there")


def test_plan() -> None:
    scene = app_stubs.Scene()
    setup(scene)
    face = front_face(scene, 0.0)
    V = app_stubs.QVector3D
    p = params_mod.normalize({})

    # The opening stands on the bottom of the wall and is centred on the click.
    origin, across, into, up, depth, corners = opening_mod.plan(
        scene, face, V(2.0, 0.0, 1.0), p)
    close(depth, 0.30, "the wall is 30 cm thick")
    close(origin.z(), 0.0, "a door stands on the floor")
    close(origin.x(), 2.0 - p["width"] / 2, "centred on the click")
    equal(len(corners), 4, "four corners")
    close((corners[1] - corners[0]).length(), p["width"],
          "the opening is the width asked for")
    close((corners[3] - corners[0]).length(), p["height"],
          "and the height asked for")

    # Slid inside the face rather than hanging off a jamb.
    _o, _a, _i, _u, _d, edge = opening_mod.plan(scene, face, V(0.05, 0, 1), p)
    check(edge[0].x() >= -1e-6,
          f"an opening near the jamb stays on the wall, got x={edge[0].x()}")

    # Too big for the wall: refused, with words.
    narrow = app_stubs.Scene()
    narrow.layers.append(app_stubs.Layer("Walls"))
    box(narrow, 0.0, 0.0, 0.0, 0.50, 0.30, 2.70, attrs={"layer": "Walls"})
    try:
        opening_mod.plan(narrow, front_face(narrow, 0.0), V(0.25, 0, 1.0), p)
        check(False, "a door wider than the wall should be refused")
    except opening_mod.OpeningError as exc:
        check("wider than the wall" in str(exc),
              f"and the reason says so: {exc}")
    try:
        opening_mod.plan(narrow, front_face(narrow, 0.0), V(0.25, 0, 1.0),
                         params_mod.normalize({"width": 0.40, "height": 3.90}))
        check(False, "a door taller than the wall should be refused")
    except opening_mod.OpeningError as exc:
        check("taller than the wall" in str(exc), f"and the reason: {exc}")

    # No wall behind it: refused rather than boring a tunnel.
    lone_scene = app_stubs.Scene()
    lone_scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 0, 2.7), V(0, 0, 2.7)])
    try:
        opening_mod.plan(lone_scene, lone_scene.mesh.faces[0], V(2.0, 0, 1.0), p)
        check(False, "a single-plane wall should be refused")
    except opening_mod.OpeningError as exc:
        check("no wall behind" in str(exc), f"and it says so: {exc}")


def test_cut_and_close() -> None:
    scene = app_stubs.Scene()
    setup(scene)
    face = front_face(scene, 0.0)
    V = app_stubs.QVector3D
    p = params_mod.normalize({})

    before_faces = len(scene.mesh.faces)
    check(scene.mesh.is_closed(), "the wall starts closed")

    origin, across, into, up, depth, corners = opening_mod.plan(
        scene, face, V(2.0, 0.0, 1.0), p)
    record = opening_mod.cut(scene, face, corners, depth)

    equal(len(scene.mesh.faces), before_faces + 4,
          "the wall keeps its faces and gains four reveals")
    check(face in scene.mesh.faces,
          "the face the user clicked is still there — it was punched, not "
          "removed")
    check(scene.mesh.is_closed(),
          "and the wall is still a closed solid after the opening")
    equal(len(record["reveals"]), 4, "four reveals recorded")
    equal(len(record["hole"]["front"]), 4, "the front rim's four corners")
    equal(len(record["hole"]["back"]), 4, "and the back rim's")

    holed = [f for f in scene.mesh.faces if f.hole_loops]
    equal(len(holed), 2, "exactly two faces carry a hole: front and back")

    # Every reveal carries the wall's own attrs, so the wall stays one object.
    reveals = [f for f in scene.mesh.faces
               if opening_mod.signature([opening_mod.as_tuple(v.position)
                                         for v in f.loop])
               in record["reveals"]]
    equal(len(reveals), 4, "the four reveals can be found again by their corners")
    for reveal in reveals:
        equal(reveal.attrs.get("mat"), "Brick",
              "a reveal keeps the wall's material")
        equal(reveal.attrs.get("layer"), "Walls", "and its layer")

    # Each reveal faces INTO the opening: the void is the new surface.
    inside = app_stubs.QVector3D(2.0, depth / 2, p["height"] / 2)
    for reveal in reveals:
        normal = reveal.normal().normalized()
        toward_opening = inside - reveal.centroid()
        check(app_stubs.QVector3D.dotProduct(normal, toward_opening) > 0,
              f"a reveal at {reveal.centroid()} faces away from the opening "
              f"(normal {normal})")

    # And closing puts the wall back exactly.
    check(opening_mod.close(scene, record), "the opening closes")
    equal(len(scene.mesh.faces), before_faces,
          "the same number of faces as before")
    check(scene.mesh.is_closed(), "and it is closed again")
    equal([f for f in scene.mesh.faces if f.hole_loops], [],
          "with no hole left behind")
    equal(face.attrs.get("mat"), "Brick",
          "the wall's face still has its material")
    equal(face.attrs.get("layer"), "Walls", "and its layer")

    # Closing twice must not double anything up.
    check(opening_mod.close(scene, record) is False,
          "closing an opening that is already closed does nothing")


def test_door_lifecycle() -> None:
    scene = app_stubs.Scene()
    setup(scene)
    viewport = app_stubs.Viewport(scene)
    face = front_face(scene, 0.0)
    V = app_stubs.QVector3D

    result = {}
    ok = object_mod.run(viewport, lambda s: result.update(
        door=object_mod.create(s, face, V(2.0, 0.0, 1.0),
                               params_mod.normalize({"threshold": 0.02}),
                               viewport=viewport)),
        "Door placed")
    check(ok, f"placing a door succeeds: {viewport.history.last_error}")

    door = result["door"]
    check(object_mod.is_door(door), "the container is a door")
    equal(door.ifc.get("class"), "IfcDoor", "and is tagged IfcDoor")
    equal(door.layer, params_mod.DEFAULT_LAYER, "on the Doors layer")
    check(scene.mesh.is_closed(), "the wall is closed around it")

    names = [k.name for k in door.children]
    check("Frame" in names and "Leaf" in names,
          f"the door has its parts: {names}")

    # A symbol of its own, on the symbol layer — separate, so a view can hide
    # it (a nested group's layer is never consulted).
    symbol = object_mod.symbol_group(scene, door)
    check(symbol is not None, "the door has a swing symbol")
    equal(symbol.layer, params_mod.normalize({})["symbol_layer"],
          "the symbol is on the plan-symbol layer")
    check(symbol in scene.groups, "as a top-level group")
    check(symbol.mesh.edges, "made of edges, not faces")
    check(not symbol.mesh.faces, "…only edges")

    # Both layers were made, so the symbol can be switched off per view.
    layer_names = {ly.name for ly in scene.layers}
    check(params_mod.DEFAULT_LAYER in layer_names, "the Doors layer exists")
    check(params_mod.normalize({})["symbol_layer"] in layer_names,
          "and the symbol's layer")

    # The door's own bookkeeping is in the document, JSON-safe and all.
    stored = scene.plugin_data[params_mod.KEY]
    json.dumps(stored)                       # would raise on a live object
    check(door.uid in stored["doors"], "the door is registered")

    # ---- Edit: new parameters, same place ----
    placed = object_mod.current_frame(door, {})
    object_mod.run(viewport, lambda s: object_mod.rebuild(
        s, door, params_mod.normalize({"handing": "right", "open_angle": 45.0,
                                       "threshold": 0.0})), "")
    equal(object_mod.door_params(door)["handing"], "right",
          "the new parameter is kept")
    after = object_mod.current_frame(door, {})
    equal(after["origin"], placed["origin"], "and the door did not move")
    check("Threshold" not in [k.name for k in door.children],
          "a parameter set to none drops its part")
    fresh_symbol = object_mod.symbol_group(scene, door)
    check(fresh_symbol is not None and fresh_symbol is not symbol,
          "the symbol was rebuilt in place, not duplicated")
    equal(len([g for g in scene.groups if g.name == "Door swing"]), 1,
          "and there is still exactly one")
    check(scene.mesh.is_closed(), "the wall is still closed after the edit")

    # ---- Erase: the door goes and the wall comes back ----
    object_mod.run(viewport, lambda s: object_mod.erase(s, door), "")
    check(door not in scene.groups, "the door is gone")
    check(object_mod.symbol_group(scene, door) is None,
          "and so is its symbol")
    check(scene.mesh.is_closed(),
          "the wall is closed again — the opening was closed on the way out")
    check(params_mod.KEY not in scene.plugin_data,
          "and the emptied bookkeeping was taken away, not left hollow")

    # ---- Undo, all the way back ----
    while viewport.history.undo():
        pass
    equal(len(scene.groups), 0, "undo takes the door and its symbol away")
    equal(scene.plugin_data, {}, "and the bookkeeping with them")
    equal(len(scene.mesh.faces), 6, "the bare wall is back")
    check(scene.mesh.is_closed(), "closed, as it started")
    equal(front_face(scene, 0.0).attrs.get("mat"), "Brick",
          "with its material")


def main() -> int:
    install_package()
    app_stubs.install()
    global params_mod, opening_mod, object_mod
    params_mod = load("params")
    globals()["geometry"] = load("geometry")
    opening_mod = load("opening")
    object_mod = load("object")

    test_axes()
    test_plan()
    test_cut_and_close()
    test_door_lifecycle()

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"openings object: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
