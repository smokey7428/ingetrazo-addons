#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
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
    built = geometry.parts(p, depth)

    for name, faces in built.items():
        check_closed(name, faces)
        check_outward(name, faces)

    clear_w, clear_h, jamb, head = geometry.frame_opening(p)
    close(clear_w, p["width"] - 2 * p["frame_w"], "the clear width")
    close(clear_h, p["height"] - p["frame_h"], "the clear height")

    # The lining is the opening less the clear hole, through the wall.
    close(geometry.volume(built["Frame"]),
          (p["width"] * p["height"] - clear_w * clear_h) * depth,
          "the lining's volume is the opening less the clear hole")

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
    close(hy, depth, "and runs to the back of the opening")
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
    centre_y = depth / 2
    thickness = 0.042

    # Closed: the leaf lies inside the opening, along x, a thin slab in y.
    closed = geometry.parts(params_mod.normalize(dict(base, open_angle=0.0,
                                                     swing="in")), depth)
    (lx, ly, _lz), (hx, hy, _hz) = geometry.bounds(closed["Leaf"])
    close(lx, jamb, "closed, the leaf starts at the left jamb")
    close(hx, jamb + clear_w, "and ends at the right jamb")
    close(hy - ly, thickness, "and is one leaf thick in y")

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
    pivot, _t, _y = geometry.hinge_and_leaf(p, depth)
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
    check(set(p) == set(params_mod.DEFAULTS),
          "a fresh door carries every parameter")
    close(p["width"], 0.90, "and the default width")

    # Rubbish falls back rather than raising — a door that cannot be rebuilt
    # because one number went bad is worse than a door at 90 degrees.
    messy = params_mod.normalize({"width": "wide", "handing": "sideways",
                                  "swing": 7, "leaf_t": float("nan"),
                                  "open_angle": 900.0, "symbol": "yes"})
    close(messy["width"], 0.90, "an unreadable width falls back")
    check(messy["handing"] == "left", "an unknown handing falls back")
    check(messy["swing"] == "in", "and an unknown swing")
    close(messy["leaf_t"], 0.042, "a NaN thickness falls back")
    close(messy["open_angle"], 179.0, "an impossible angle is clamped")
    check(messy["symbol"] is True, "and a truthy symbol stays on")

    # Out-of-range numbers are clamped, not refused.
    clamped = params_mod.normalize({"width": 99.0, "threshold": -5.0,
                                    "handle": 40.0})
    close(clamped["width"], 4.0, "an absurd width clamps to the limit")
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


def main() -> int:
    install_package()
    global params_mod, geometry
    params_mod = load("params")
    geometry = load("geometry")

    test_prism()
    test_whole_door()
    test_handing_and_swing()
    test_symbol()
    test_params()

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"openings geometry: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
