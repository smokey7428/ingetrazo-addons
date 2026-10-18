#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Check the wall's model and its multi-skin geometry — no Qt, no IngeTrazo.

What a wall has to get right:

* **every skin is a closed solid with a positive volume** — the same condition
  ``core/bim.py`` asks before it will report a quantity, so a skin that fails it
  would silently have no volume in a take-off;
* **the skins' volumes are the arithmetic**: length × height × thickness each,
  and they add up to length × height × the wall's full thickness;
* **the skins are centred on the path**, half on either side, the way a wall is
  drawn in a plan;
* **a corner mitres**: the two runs meet on the mitre line, the outer skin of a
  turn stops short and the inner one runs past by the same amount, and the
  volume loses exactly the square the two runs would have shared.

Usage:  python3 dev/tests/test_openings_walls.py
"""
from __future__ import annotations

import importlib.util
import math
import sys
import types
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
          f"{message}: got {got!r}, want {want!r} (tol {tol})")


def close_point(got, want, message: str, tol: float = 1e-9) -> None:
    ok = (len(got) >= 2 and len(want) >= 2
          and abs(got[0] - want[0]) <= tol and abs(got[1] - want[1]) <= tol)
    check(ok, f"{message}: got {got!r}, want {want!r}")


def load(name: str):
    full = f"ingetrazo_plugin_openings.{name}"
    spec = importlib.util.spec_from_file_location(full, EXT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    setattr(sys.modules["ingetrazo_plugin_openings"], name, module)
    spec.loader.exec_module(module)
    return module


def install_package() -> None:
    package = types.ModuleType("ingetrazo_plugin_openings")
    package.__path__ = [str(EXT)]
    sys.modules["ingetrazo_plugin_openings"] = package


# ---- the checks used on every part ------------------------------------------
def closed(faces) -> bool:
    counts: dict = {}
    for loop, holes in faces:
        for ring in (loop, *holes):
            count = len(ring)
            for i in range(count):
                a, b = ring[i], ring[(i + 1) % count]
                key = (a, b) if a <= b else (b, a)
                counts[key] = counts.get(key, 0) + 1
    return bool(counts) and all(n == 2 for n in counts.values())


def check_solid(name: str, faces) -> float:
    check(bool(faces), f"{name} has faces")
    check(closed(faces), f"{name} is a closed solid on its own")
    volume = geometry.volume(faces)
    check(volume > 1e-9, f"{name} encloses a positive volume, got {volume!r}")
    return volume


# ---- the model --------------------------------------------------------------
def test_model() -> None:
    w = walls.defaults()
    equal(w["kind"], "wall", "a fresh wall says what it is")
    equal(w["type"], "spouwmuur", "and is the cavity wall to begin with")
    equal(len(w["skins"]), 3, "three skins: outside, insulation, inside")
    close(walls.total_thickness(w), 0.300, "a 300 mm wall")
    close(w["height"], 2.700, "2.7 m high")
    equal([s["name"] for s in w["skins"]],
          ["Buitenblad", "Isolatie", "Binnenblad"],
          "named the way the trade names them")

    # Centred on the path: half the wall on either side.
    spans = [(round(a, 9), round(b, 9)) for _s, a, b in walls.offsets(w)]
    equal(spans, [(-0.15, -0.05), (-0.05, 0.05), (0.05, 0.15)],
          "the skins straddle the line the wall is drawn along")

    # Tolerant, like the openings: rubbish lands on the standard.
    messy = walls.normalize({"type": "nonsense", "height": "tall",
                             "skins": [{"thickness": "thick"},
                                       {"name": "Ok", "thickness": 0.1}]})
    equal(messy["type"], "spouwmuur", "an unknown build-up falls back")
    close(messy["height"], 2.700, "an unreadable height falls back")
    equal([s["name"] for s in messy["skins"]], ["Ok"],
          "a skin with no thickness is dropped")

    # JSON-safe, so it survives group.ext and the .igz.
    import json
    check(walls.normalize(json.loads(json.dumps(w))) == w,
          "the wall survives a JSON round trip unchanged")

    # Validation says what is wrong, in words.
    empty = walls.normalize({"skins": [{"name": "x", "thickness": 0}]})
    check(walls.validate(empty), "a wall of skins with no thickness is refused")
    no_path = walls.normalize({})
    check(any("two points" in problem
              for problem in walls.validate(no_path)),
          "so is a wall with no path")


def test_straight() -> None:
    w = walls.normalize({"type": "binnenwand", "height": 2.7,
                         "path": [[0, 0], [4, 0]]})
    built = wall_geometry.skin_faces(w)
    equal(list(built), ["Binnenblad"], "one skin, one part")
    volume = check_solid("Binnenblad", built["Binnenblad"])
    close(volume, 4.0 * 0.100 * 2.7, "4 m × 2.7 m × 100 mm")
    check(closed(wall_geometry.skin_faces(w)["Binnenblad"]),
          "and it is closed")

    # Centred on the line it was drawn along.
    (_lx, ly, lz), (_hx, hy, hz) = wall_geometry.bounds(built)
    close(ly, -0.05, "the skin starts 50 mm left of the path")
    close(hy, 0.05, "and ends 50 mm right of it")
    close(lz, 0.0, "standing on its base")
    close(hz, 2.7, "and reaching its height")


def test_three_skins() -> None:
    w = walls.normalize({"height": 2.7, "path": [[0, 0], [4, 0]]})
    built = wall_geometry.skin_faces(w)
    equal(list(built), ["Buitenblad", "Isolatie", "Binnenblad"],
          "each skin is its own part, in build-up order")

    total = 0.0
    for skin, faces in built.items():
        total += check_solid(skin, faces)
        close(geometry.volume(faces), 4.0 * 0.100 * 2.7,
              f"{skin} is 4 m × 2.7 m × 100 mm")
    close(total, 4.0 * 0.300 * 2.7,
          "and three skins make the 300 mm wall")
    close(wall_geometry.volume(built), 4.0 * 0.300 * 2.7,
          "the wall's own volume agrees")


def test_mitre() -> None:
    """A 90-degree turn meets on the mitre line, and loses only the shared square."""
    w = walls.normalize({"type": "binnenwand", "height": 2.7,
                         "path": [[0, 0], [4, 0], [4, 3]]})
    half = walls.total_thickness(w) * 0.5

    # Travelling east then north is a LEFT turn, so the left side is the inside.
    close(wall_geometry.corner(w, 1, +half)[0], 4.0 - half,
          "the inside corner stops short of the vertex in x")
    close(wall_geometry.corner(w, 1, +half)[1], 0.0 + half,
          "…and sits on the first run's offset line")
    close(wall_geometry.corner(w, 1, -half)[0], 4.0 + half,
          "the outside corner runs past it in x")
    close(wall_geometry.corner(w, 1, -half)[1], 0.0 - half,
          "…and sits on the other offset line")

    # The ends of the path are square across, not mitred.
    close_point(wall_geometry.corner(w, 0, +half), (0.0, half),
                "the path's start is cut square")
    close_point(wall_geometry.corner(w, 2, +half), (4.0 - half, 3.0),
                "and so is its end")

    built = wall_geometry.skin_faces(w)
    volume = check_solid("Binnenblad", built["Binnenblad"])
    # The mitre line passes through the vertex, so each run keeps exactly its
    # own length — nothing is lost to the turn and nothing gained. (A squared
    # butt joint would overlap by the shared square; a mitre does not.)
    expected = 0.100 * (4.0 + 3.0) * 2.7
    close(volume, expected,
          "a mitred turn keeps exactly the two runs' own areas")

    # A three-skin wall turns too: the skin on the outside of the turn is
    # longer, the one on the inside shorter, and the wall's total is conserved
    # — which is the whole point of mitring every skin rather than the middle.
    thick = walls.normalize({"height": 2.7, "path": [[0, 0], [4, 0], [4, 3]]})
    outer = inner = 0.0
    for name, faces in wall_geometry.skin_faces(thick).items():
        check_solid(name, faces)
        if name == "Buitenblad":
            outer = geometry.volume(faces)
        if name == "Binnenblad":
            inner = geometry.volume(faces)
    check(outer > expected, f"the outside of the turn is longer: {outer}")
    check(inner < expected, f"and the inside is shorter: {inner}")
    close(wall_geometry.volume(wall_geometry.skin_faces(thick)),
          0.300 * (4.0 + 3.0) * 2.7,
          "but the wall as a whole keeps its 300 mm × 7 m × 2.7 m")


def test_short_segment() -> None:
    """A segment too short to mitre is squared off rather than turned inside out."""
    w = walls.normalize({"height": 2.7,
                         "path": [[0, 0], [0.2, 0], [0.2, 3]]})
    check(not wall_geometry.joint_ok(w, 1),
          "0.2 m of wall cannot hold a 300 mm mitre")
    built = wall_geometry.skin_faces(w)
    for skin, faces in built.items():
        check_solid(skin, faces)
    equal(len(built), 3, "and the wall still builds, all three skins")

    # A gentle turn at a good length does mitre.
    long_wall = walls.normalize({"height": 2.7,
                                 "path": [[0, 0], [4, 0], [7, 2]]})
    check(wall_geometry.joint_ok(long_wall, 1),
          "a 7 m run at walking pace does mitre")


def test_wall_object() -> None:
    """A wall in the document: one container, one part per skin, regenerating."""
    scene = app_stubs.Scene()
    viewport = app_stubs.Viewport(scene)
    w = walls.normalize({"height": 2.7, "path": [[0, 0], [4, 0], [4, 3]]})

    made: dict = {}
    check(object_mod.run(viewport, lambda s: made.update(
        wall=wall_object.create(s, w)), "Wall drawn", label="Wall"),
          f"drawing a wall succeeds: {viewport.history.last_error}")
    wall = made["wall"]

    equal(wall.ifc.get("class"), "IfcWall", "the container is tagged IfcWall")
    equal([k.name for k in wall.children],
          ["Buitenblad", "Isolatie", "Binnenblad"],
          "one part per skin, named as the build-up names them")
    check(wall_object.is_wall(wall), "and it knows it is one of our walls")
    equal(wall_object.data_of(wall).get("kind"), "wall",
          "its kind is stored with it")

    # Each skin's part is a closed solid on its own, so a take-off can measure
    # it; the materials were made for them.
    for child in wall.children:
        faces = [([v.position.toTuple() for v in f.loop],
                  [[v.position.toTuple() for v in h] for h in f.hole_loops])
                 for f in child.mesh.faces]
        check_solid(child.name, faces)
    for name in ("Brick", "Insulation", "Block"):
        check(name in scene.materials, f"the {name} material was made")

    # ---- regenerate: same wall, new numbers ----
    changed = walls.normalize(dict(
        wall_object.wall_params(wall),
        skins=[{"name": "Buitenblad", "thickness": 0.15, "material": "Brick"},
               {"name": "Binnenblad", "thickness": 0.10, "material": "Block"}],
        height=3.0))
    object_mod.run(viewport, lambda s: wall_object.regenerate(s, wall, changed),
                   label="Wall")
    equal(wall_object.walls.total_thickness(wall_object.wall_params(wall)),
          0.250, "the new build-up is 250 mm")
    equal([k.name for k in wall.children], ["Buitenblad", "Binnenblad"],
          "and it has two skins now, not three")
    equal(wall_object.wall_params(wall)["height"], 3.0, "and is 3 m high")

    # ---- erase, and undo all the way ----
    object_mod.run(viewport, lambda s: wall_object.erase(s, wall), label="Wall")
    equal(scene.groups, [], "the wall is gone")
    while viewport.history.undo():
        pass
    equal(scene.groups, [], "undo leaves no wall behind")
    equal(scene.plugin_data, {}, "and nothing in the document data")


def main() -> int:
    install_package()
    app_stubs.install()
    global profiles, params, geometry, walls, wall_geometry, wall_object
    global object_mod
    profiles = load("profiles")
    params = load("params")
    geometry = load("geometry")
    walls = load("walls")
    wall_geometry = load("wall_geometry")
    opening = load("opening")
    object_mod = load("object")
    wall_object = load("wall_object")

    test_model()
    test_straight()
    test_three_skins()
    test_mitre()
    test_short_segment()
    test_wall_object()

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"openings walls: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
