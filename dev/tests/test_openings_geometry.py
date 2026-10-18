#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Check the door's geometry and its parameters — no Qt, no IngeTrazo.

The geometry is built from plain coordinates on purpose, so this can check the
things that decide whether a door is a door:

* every part is a **closed solid with a positive volume** — which is what the
  BIM takeoff reads, and what tells an outward-wound face from an inward one;
* the volumes match the arithmetic, so a lining is not accidentally solid;
* the leaf **actually turns**: handed left or right, opening in or out, and by
  the angle asked for;
* the swing symbol's arc is centred on the hinge and has the leaf's radius.

Usage:  python3 dev/tests/test_openings_geometry.py
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent.parent / "extensions" / "openings"

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def close(got, want, message: str, tol: float = 1e-6) -> None:
    check(abs(got - want) <= tol,
          f"{message}: got {got!r}, want {want!r} (tol {tol})")


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


def load(name: str):
    """Import a module of the extension by path, the way IngeTrazo would.

    Registered under the package's dotted name, so ``from . import params``
    inside the module resolves the same way it does in the application.
    """
    full = f"ingetrazo_plugin_openings.{name}"
    spec = importlib.util.spec_from_file_location(full, EXT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    package = sys.modules["ingetrazo_plugin_openings"]
    setattr(package, name, module)
    spec.loader.exec_module(module)
    return module


def install_package() -> None:
    """A stand-in for the package itself, without running __init__ (a door
    extension's __init__ builds Qt panels; these tests must not need Qt)."""
    import types
    package = types.ModuleType("ingetrazo_plugin_openings")
    package.__path__ = [str(EXT)]
    sys.modules["ingetrazo_plugin_openings"] = package


# ---- faces ------------------------------------------------------------------
def ring_pairs(loop):
    return [(loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))]


def check_closed(name: str, faces) -> None:
    """Every edge of the set borders exactly two faces of the set, counting
    direction — the same test core/bim.py uses to decide it may report a
    volume, applied to our own faces."""
    counts: dict = {}
    for loop, holes in faces:
        for ring in (loop, *holes):
            for a, b in ring_pairs(ring):
                key = (a, b) if a <= b else (b, a)
                counts[key] = counts.get(key, 0) + 1
    bad = [key for key, n in counts.items() if n != 2]
    check(not bad, f"{name} is not closed on its own: {len(bad)} bad edges "
                   f"(first: {bad[:2]})")


def check_outward(name: str, faces) -> None:
    """A closed solid wound outward has a positive volume. A face turned the
    wrong way subtracts twice its own tetrahedron, so this catches it."""
    from_volume = geometry.volume(faces)
    check(from_volume > 1e-9,
          f"{name} should enclose a positive volume, got {from_volume!r}")


# ---- the tests --------------------------------------------------------------
def test_prism() -> None:
    """A slab with a hole is a ring: its volume is the difference."""
    outline = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]
    inner = [(0.5, 0.25), (1.5, 0.25), (1.5, 0.75), (0.5, 0.75)]
    ring = geometry.prism(outline, [inner], 0.0, 0.3, plane="xz")
    check_closed("a ring", ring)
    check_outward("a ring", ring)
    close(geometry.volume(ring), (2.0 * 1.0 - 1.0 * 0.5) * 0.3,
          "the ring's volume is the outer slab less the hole")

    plain = geometry.prism(outline, [], 0.0, 0.3, plane="xz")
    check_closed("a plain slab", plain)
    close(geometry.volume(plain), 2.0 * 0.3,
          "a slab of 2.0 x 1.0 swept 0.3 along y encloses 0.6")

    # The same shape swept the other way is the same solid.
    up = geometry.prism(outline, [], 0.0, 0.3, plane="xy")
    check_closed("a slab swept along z", up)
    check_outward("a slab swept along z", up)
    close(geometry.volume(up), 2.0 * 0.3, "…and encloses the same volume")

    # Winding of the input must not matter: the faces come out oriented.
    shuffled = geometry.prism(list(reversed(outline)), [], 0.0, 0.3, plane="xz")
    check_outward("a slab given a clockwise outline", shuffled)


def test_whole_door() -> None:
    p = params_mod.normalize({"threshold": 0.02, "handle": 1.05})
    depth = 0.30
    held = params_mod.frame_depth(p, depth)
    close(held, 0.114, "the frame is 114 mm of kozijnhout, not the wall")
    built = geometry.parts(p, depth)

    for name, faces in built.items():
        check_closed(name, faces)
        check_outward(name, faces)

    clear_w, clear_h, jamb, head = geometry.frame_opening(p)
    close(clear_w, p["width"] - 2 * p["frame_w"], "the clear width")
    close(clear_h, p["height"] - p["frame_h"], "the clear height")

    # The lining is the opening less the clear hole, through the wall.
    close(geometry.volume(built["Frame"]),
          (p["width"] * p["height"] - clear_w * clear_h) * held,
          "the frame's volume is the opening less the clear hole, 114 mm deep")

    # The leaf is a slab of the clear size, its thickness asked for.
    close(geometry.volume(built["Leaf"]),
          clear_w * clear_h * p["leaf_t"],
          "the leaf's volume")

    # A threshold spans the clear width, the wall depth and its own height.
    close(geometry.volume(built["Threshold"]),
          clear_w * depth * p["threshold"], "the threshold's volume")

    # Everything sits inside the opening, and the leaf may swing past it.
    (lx, ly, lz), (hx, hy, hz) = geometry.bounds(built["Frame"])
    close(lx, 0.0, "the lining starts at x = 0")
    close(hx, p["width"], "and ends at the opening's far jamb")
    close(ly, 0.0, "the lining starts on the clicked face")
    close(hy, held, "and runs its own 114 mm into the wall")
    close(hz, p["height"], "the lining reaches the head of the opening")

    # The leaf reaches the floor (a door has no bottom lining member) and
    # stops under the head lining, which is what the parameter buys.
    (_lx2, _ly2, lz2), (_hx2, _hy2, hz2) = geometry.bounds(built["Leaf"])
    close(lz2, 0.0, "the leaf reaches the floor")
    close(hz2, clear_h, "and stops under the head lining")
    close(hz2, p["height"] - p["frame_h"], "…by exactly the head lining")


def test_handing_and_swing() -> None:
    """The leaf turns the right way for each of the four combinations.

    The assertions are exact rather than loose: the free edge of a leaf open
    90 degrees lands exactly ``clear_w`` from the hinge, which is the property
    the swing symbol is drawn from — if the two ever disagreed, the plan would
    show a door that does not match its arc.
    """
    depth = 0.30
    base = {"width": 0.90, "height": 2.10, "frame_w": 0.06}
    clear_w = 0.90 - 2 * 0.06
    jamb = 0.06
    base_p = params_mod.normalize(base)
    thickness = base_p["leaf_t"]
    held = params_mod.frame_depth(base_p, depth)
    y0 = (held - thickness) * 0.5
    centre_y = y0 + thickness * 0.5        # the hinge runs through the middle

    # Closed: the leaf lies inside the opening, along x, a thin slab in y.
    closed = geometry.parts(params_mod.normalize(dict(base, open_angle=0.0,
                                                     swing="in")), depth)
    (lx, ly, _lz), (hx, hy, _hz) = geometry.bounds(closed["Leaf"])
    close(lx, jamb, "closed, the leaf starts at the left jamb")
    close(hx, jamb + clear_w, "and ends at the right jamb")
    close(hy - ly, thickness, "and is one leaf thick in y")
    close(ly, y0, "sitting in the frame's 114 mm of depth")

    def leaf_box(p):
        return geometry.bounds(geometry.parts(params_mod.normalize(p), depth)
                               ["Leaf"])

    # Left-handed, opening away from the clicked face: the free edge goes to
    # +y and the leaf ends up lying across the opening.
    (lx, ly, _lz), (hx, hy, _hz) = leaf_box(dict(base, handing="left",
                                                 swing="in", open_angle=90.0))
    close(hy, centre_y + clear_w, "a left-hand leaf open 90 degrees reaches "
                                  "clear_w into the wall")
    close(hx - lx, thickness, "…and lies across the opening, one leaf thick")
    check(lx <= jamb and hx >= jamb,
          f"its hinge edge straddles the left jamb, got {lx}..{hx}")

    # …opening the other way: the free edge goes to -y, out of the wall.
    (_lx, ly, _lz), (_hx, hy, _hz) = leaf_box(dict(base, handing="left",
                                                   swing="out", open_angle=90.0))
    close(ly, centre_y - clear_w, "a left-hand leaf opening out reaches "
                                  "clear_w out of the wall")
    close(hy, centre_y, "…and its hinge edge stays on the centre line")

    # Right-handed: the hinge is on the far jamb, so the leaf is the mirror of
    # the left-hand one — not the same door.
    (lx, ly, _lz), (hx, hy, _hz) = leaf_box(dict(base, handing="right",
                                                 swing="out", open_angle=90.0))
    close(ly, centre_y - clear_w, "a right-hand leaf opening out reaches just "
                                  "as far")
    check(hx >= jamb + clear_w and lx <= jamb + clear_w,
          f"and hangs on the right jamb, got {lx}..{hx}")

    # Half-open is half the reach: the angle means something. The leaf's
    # extreme is its far corner, half a thickness across from the free edge.
    (_lx, _ly, _lz), (_hx, hy, _hz) = leaf_box(dict(base, handing="left",
                                                    swing="in",
                                                    open_angle=45.0))
    turn = math.radians(45.0)
    close(hy, centre_y + clear_w * math.sin(turn)
          + (thickness / 2) * math.cos(turn),
          "at 45 degrees the free corner is sin(45) of the way out, plus half "
          "a leaf of thickness across", tol=1e-9)

    # The four combinations are four different places for the leaf.
    places = set()
    for handing in ("left", "right"):
        for swing in ("in", "out"):
            (lx, ly, _lz), (hx, hy, _hz) = leaf_box(
                dict(base, handing=handing, swing=swing, open_angle=90.0))
            places.add((round(lx, 3), round(ly, 3), round(hx, 3), round(hy, 3)))
    check(len(places) == 4,
          f"the four handedness/swing combinations should be four different "
          f"doors, got {len(places)}")

    # The signed rotation agrees with where the leaf landed.
    turn = params_mod.swing_angle(params_mod.normalize(
        dict(base, handing="left", swing="in", open_angle=90.0)))
    close(turn, math.pi / 2, "left, in, 90 degrees is a quarter turn towards +y")
    turn = params_mod.swing_angle(params_mod.normalize(
        dict(base, handing="right", swing="in", open_angle=90.0)))
    close(turn, -math.pi / 2,
          "right, in, 90 degrees turns the other way about the same axis")


def test_symbol() -> None:
    """The arc is centred on the hinge, with the leaf's radius."""
    depth = 0.30
    p = params_mod.normalize({"handing": "left", "swing": "in",
                              "open_angle": 90.0, "symbol_z": 0.0})
    pivot, _y0, _t, _y1 = geometry.hinge_and_panel(
        p, params_mod.frame_depth(p, depth))
    clear_w, _h, _jamb, _head = geometry.frame_opening(p)

    segments = geometry.swing_symbol(p, depth)
    check(len(segments) >= 8, f"a 90-degree arc wants several segments, "
                              f"got {len(segments)}")
    for a, b in segments:
        for point in (a, b):
            radius = math.hypot(point[0] - pivot[0], point[1] - pivot[1])
            close(radius, clear_w, "every point of the arc is the leaf's "
                                   "width from the hinge", tol=1e-9)
            close(point[2], 0.0, "and lies at the symbol's height")

    # It sweeps from the closed position to the open one.
    first = segments[0][0]
    last = segments[-1][1]
    close(first[0], pivot[0] + clear_w, "the arc starts where the closed leaf "
                                        "ends", tol=1e-9)
    close(first[1], pivot[1], "…on the opening's centre line", tol=1e-9)
    close(last[0], pivot[0], "and finishes where the open leaf's edge is",
          tol=1e-9)
    close(last[1], pivot[1] + clear_w, "…a quarter turn away", tol=1e-9)

    # Turned off, there is no symbol; the opening outline follows it.
    off = params_mod.normalize({"symbol": False})
    check(geometry.swing_symbol(off, depth) == [], "no symbol when asked for none")
    check(geometry.outline_symbol(off, depth) == [],
          "and no outline either")
    outline = geometry.outline_symbol(p, depth)
    check(len(outline) == 4, f"the opening outline is a quad, got {len(outline)}")
    for point in outline:
        close(point[2], 0.0, "the outline sits at the symbol's height")


def test_params() -> None:
    """Normalising is tolerant; validating is honest."""
    p = params_mod.normalize(None)
    check(set(p) == set(params_mod.defaults()),
          "a fresh door carries every parameter")
    close(p["width"], 1.064, "and the default width — a 930 leaf in a 67 mm "
                             "frame")

    # Rubbish falls back rather than raising — a door that cannot be rebuilt
    # because one number went bad is worse than a door at 90 degrees.
    messy = params_mod.normalize({"width": "wide", "handing": "sideways",
                                  "swing": 7, "leaf_t": float("nan"),
                                  "open_angle": 900.0, "symbol": "yes"})
    close(messy["width"], 1.064, "an unreadable width falls back to the "
                                 "catalogue's")
    check(messy["handing"] == "left", "an unknown handing falls back")
    check(messy["swing"] == "in", "and an unknown swing")
    close(messy["leaf_t"], 0.042, "a NaN thickness falls back")
    close(messy["open_angle"], 179.0, "an impossible angle is clamped")
    check(messy["symbol"] is True, "and a truthy symbol stays on")

    # Out-of-range numbers are clamped, not refused.
    clamped = params_mod.normalize({"width": 99.0, "threshold": -5.0,
                                    "handle": 40.0})
    close(clamped["width"], 6.0, "an absurd width clamps to the limit")
    close(clamped["threshold"], 0.0, "a negative threshold clamps to none")
    close(clamped["handle"], 2.5, "an absurd handle height clamps")

    # JSON-safe, so it survives group.ext and the .igz.
    import json
    round_trip = json.loads(json.dumps(p))
    check(params_mod.normalize(round_trip) == p,
          "the parameters survive a JSON round trip unchanged")

    # Validation catches the combinations that do not add up.
    check(params_mod.validate(p) == [], f"the defaults are sound: "
                                        f"{params_mod.validate(p)}")
    too_narrow = params_mod.normalize({"width": 0.30, "frame_w": 0.20})
    check(any("clear opening" in problem
              for problem in params_mod.validate(too_narrow)),
          "a lining that eats the opening is reported")
    bad_handle = params_mod.normalize({"handle": 2.50, "height": 1.20})
    check(params_mod.validate(bad_handle),
          "a handle outside the leaf is reported")
    check("mm" in params_mod.describe(p), "the description carries the size")


def test_window() -> None:
    """The Dutch standards, and that a window is the same machinery.

    The numbers are the ones a wooden window is actually made of: kozijnhout
    67 × 114 mm for the frame, raamhout 54 × 67 mm for a sash that opens, and
    20 mm glazing in both. If any of these drift, the frames a carpenter gets
    do not fit the hole the wall was cut for.
    """
    fixed = params_mod.normalize({"kind": "window"})
    equal(fixed["type"], "fixed", "a fresh window is a fixed one")
    close(fixed["width"], 1.000, "a 1000 mm wide frame")
    close(fixed["height"], 1.500, "1500 mm high")
    close(fixed["sill"], 0.900, "standing on a 900 mm sill")
    close(fixed["frame_w"], 0.067, "kozijnhout 67 mm wide")
    close(fixed["frame_h"], 0.067, "the head is the same section")
    close(fixed["frame_b"], 0.067, "and so is the bottom member")
    close(fixed["frame_depth"], 0.114, "and 114 mm deep")
    close(fixed["glass_t"], 0.020, "with 20 mm glass")
    check(not params_mod.moves(fixed), "a vast raam does not open")
    check(fixed["symbol"] is False, "so it has no swing symbol")

    swing = params_mod.normalize({"kind": "window", "type": "swing"})
    close(swing["sash_w"], 0.054, "raamhout is 54 mm wide")
    close(swing["sash_d"], 0.067, "and 67 mm deep")
    close(swing["glass_t"], 0.020, "with the same 20 mm glass")
    close(swing["frame_w"], 0.067, "inside the same kozijn")
    check(params_mod.moves(swing), "a draairaam opens")
    check(swing["symbol"] is True, "so it has a swing symbol")
    close(swing["open_angle"], 90.0, "standing open at 90 degrees")
    check("Draairaam" in profiles_mod.label("window", "swing"),
          "and it is named the way the Dutch name it")
    check(profiles_mod.label("door", "hinged").startswith("Stompe deur"),
          "as is the door")

    # A door is untouched by any of this: its own sections, its own sizes.
    door = params_mod.normalize({})
    close(door["frame_w"], 0.067, "the door frame section")
    close(door["frame_b"], 0.0, "a door has no bottom member")
    close(door["frame_depth"], 0.114, "and its frame is a 114 mm kozijn")
    close(door["width"], 1.064, "a 930 leaf in a 67 mm frame")
    check(door["glass_t"] == 0.0, "a door is not glazed by default")

    # The frame is as deep as its section, not as deep as the wall — which is
    # the one thing that really differs from a door lining.
    depth = 0.30
    built = geometry.parts(fixed, depth)
    check(set(built) == {"Frame", "Glass"},
          f"a fixed window is a frame and its glass: {sorted(built)}")
    for name, faces in built.items():
        check_closed(name, faces)
        check_outward(name, faces)
    clear_w, clear_h, _jamb, bottom = geometry.frame_opening(fixed)
    close(clear_w, 1.000 - 2 * 0.067, "the clear width")
    close(clear_h, 1.500 - 2 * 0.067, "the clear height, both members counted")
    close(bottom, 0.067, "the glass starts above the bottom member")
    close(geometry.volume(built["Frame"]),
          (1.000 * 1.500 - clear_w * clear_h) * 0.114,
          "the kozijn is 114 mm deep, not the 300 mm of wall")
    close(geometry.volume(built["Glass"]), clear_w * clear_h * 0.020,
          "the glass is the whole opening, 20 mm thick")
    (_lx, ly, _lz), (_hx, hy, hz) = geometry.bounds(built["Frame"])
    close(ly, 0.0, "the frame sits on the face that was clicked")
    close(hy, 0.114, "and stops 114 mm into the wall")
    close(hz, 1.500, "reaching the head of the opening")

    # A draairaam: a sash with the glass set in it.
    swung = geometry.parts(
        params_mod.normalize({"kind": "window", "type": "swing",
                              "open_angle": 0.0}), depth)
    check(set(swung) == {"Frame", "Sash", "Glass"},
          f"a draairaam has a sash to open: {sorted(swung)}")
    for name, faces in swung.items():
        check_closed(name, faces)
        check_outward(name, faces)
    inset = 0.054
    glass_w = clear_w - 2 * inset
    glass_h = clear_h - 2 * inset
    close(geometry.volume(swung["Sash"]),
          (clear_w * clear_h - glass_w * glass_h) * 0.067,
          "the sash is a 54 mm frame, 67 mm deep")
    close(geometry.volume(swung["Glass"]), glass_w * glass_h * 0.020,
          "and the glass is what the sash leaves it")

    # Closed it is a thin section; open 90° it lies across the opening, which
    # is what the arc in the plan is drawn from.
    closed = geometry.bounds(swung["Sash"])
    opened = geometry.bounds(geometry.parts(
        params_mod.normalize({"kind": "window", "type": "swing",
                              "open_angle": 90.0}), depth)["Sash"])
    check(closed[1][1] - closed[0][1] < 0.10,
          f"closed, the sash is one section deep: {closed}")
    check(opened[1][1] - opened[0][1] > clear_w * 0.9,
          f"open 90 degrees it reaches across the opening: {opened}")

    swing_p = params_mod.normalize({"kind": "window", "type": "swing"})
    pivot, _y0, _t, _y1 = geometry.hinge_and_panel(
        swing_p, params_mod.frame_depth(swing_p, depth))
    segments = geometry.swing_symbol(swing_p, depth)
    check(segments, "the draairaam has an arc")
    for a, b in segments:
        for point in (a, b):
            close(math.hypot(point[0] - pivot[0], point[1] - pivot[1]),
                  clear_w, "the arc is the sash's width from the hinge",
                  tol=1e-9)
    check(geometry.swing_symbol(fixed, depth) == [],
          "and a fixed window has none")

    # Validation: a sash section that leaves no room for glass is refused.
    crowded = params_mod.normalize({"kind": "window", "type": "swing",
                                    "width": 0.40, "sash_w": 0.090})
    check(any("no room for glass" in problem
              for problem in params_mod.validate(crowded)),
          f"a sash with no room for glass is reported: "
          f"{params_mod.validate(crowded)}")


def main() -> int:
    install_package()
    global params_mod, geometry, profiles_mod
    profiles_mod = load("profiles")
    params_mod = load("params")
    geometry = load("geometry")

    test_prism()
    test_whole_door()
    test_handing_and_swing()
    test_symbol()
    test_params()
    test_window()

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"openings geometry: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
