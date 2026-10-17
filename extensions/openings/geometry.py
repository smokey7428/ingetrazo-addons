# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The door's parts, as plain coordinates.

Every part is built here as a list of ``(loop, holes)`` faces of
``(x, y, z)`` tuples in the door's own coordinates, so the whole of the
geometry can be tested without Qt, without a scene and without IngeTrazo:

    x — along the wall, 0 at the left jamb of the opening
    y — into the wall, 0 on the face the user clicked
    z — up, 0 on the floor

Only :mod:`openings.object` turns these into meshes. Nothing here imports from
the application, and nothing here has side effects.

The parts are closed solids, so each one has a real volume — which is what the
BIM layer's takeoff reads, and the reason the parts are built as prisms rather
than as a pile of faces.
"""
from __future__ import annotations

import math

from . import params as params_mod

#: A face: an outer loop and any holes, each a list of 3D points.
Face = tuple

#: How far a probe is pushed off an edge to ask which side the material is on.
_EPS = 1e-6

#: An arc is a polyline, as everywhere else in IngeTrazo: there are no analytic
#: curves, so the symbol is straight segments like the Circle and Arc tools.
_ARC_STEP_DEG = 6.0
_ARC_MIN_SEGMENTS = 8


# ---- small vector helpers (tuples, so a test needs nothing) -----------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _newell(loop) -> tuple:
    """The polygon's normal, unnormalised (Newell's method)."""
    n = [0.0, 0.0, 0.0]
    count = len(loop)
    for i in range(count):
        current, nxt = loop[i], loop[(i + 1) % count]
        n[0] += (current[1] - nxt[1]) * (current[2] + nxt[2])
        n[1] += (current[2] - nxt[2]) * (current[0] + nxt[0])
        n[2] += (current[0] - nxt[0]) * (current[1] + nxt[1])
    return (n[0], n[1], n[2])


def _oriented(loop, want):
    """``loop`` wound so its normal runs along ``want`` (or against it)."""
    return list(reversed(loop)) if _dot(_newell(loop), want) < 0 else list(loop)


#: Public name: a caller outside this module (the wall opening, which has to
#: orient the reveals it adds to a wall) needs the same guarantee.
oriented = _oriented


def _oriented_against(loop, want):
    """``loop`` wound so its normal runs against ``want`` — how a hole in a
    face is wound, so the two are not coplanar-but-contradictory."""
    return list(reversed(loop)) if _dot(_newell(loop), want) > 0 else list(loop)


def _point_in_polygon(point, poly) -> bool:
    """Crossing test in the plane, used only to tell an outer loop from a hole."""
    u, v = point
    inside = False
    count = len(poly)
    for i in range(count):
        u0, v0 = poly[i]
        u1, v1 = poly[(i + 1) % count]
        if (v0 > v) != (v1 > v):
            if u0 + (v - v0) * (u1 - u0) / (v1 - v0) > u:
                inside = not inside
    return inside


# ---- the one solid-builder --------------------------------------------------
def _to3d_xz(u, v, w):
    """Plane point (x, z) swept along y."""
    return (u, w, v)


def _to3d_xy(u, v, w):
    """Plane point (x, y) swept along z."""
    return (u, v, w)


def prism(outline, holes, start: float, end: float, plane: str = "xz") -> list:
    """A closed slab: ``outline`` minus ``holes``, swept from ``start`` to
    ``end`` along the plane's normal, every face wound outward.

    ``plane="xz"`` sweeps along y (a lining through a wall); ``plane="xy"``
    sweeps along z (a leaf standing up). The side walls' outward direction is
    found by probing just off each edge and asking whether that point is
    inside the loop — which is why a hole's walls come out facing into the
    hole, as they must for the solid to be closed.
    """
    to3d = _to3d_xz if plane == "xz" else _to3d_xy
    # The sweep direction, in 3D, and the two cap normals.
    if plane == "xz":
        sweep = (0.0, 1.0, 0.0)
    else:
        sweep = (0.0, 0.0, 1.0)
    lo = (-sweep[0], -sweep[1], -sweep[2])

    faces: list = []
    outer = [(float(u), float(v)) for u, v in outline]
    inners = [[(float(u), float(v)) for u, v in h] for h in holes]

    # The two caps: outer along +/- the sweep, holes wound against them.
    faces.append((_oriented([to3d(u, v, start) for u, v in outer], lo),
                  [_oriented_against([to3d(u, v, start) for u, v in h], lo)
                   for h in inners]))
    faces.append((_oriented([to3d(u, v, end) for u, v in outer], sweep),
                  [_oriented_against([to3d(u, v, end) for u, v in h], sweep)
                   for h in inners]))

    # The side walls. The outer loop's face the world; a hole's face the hole.
    # The quad as built runs the loop one way and the sweep the other, so its
    # normal comes out opposite the one just worked out — `_oriented` turns it
    # the right way, which is what windowizer's `_face` does for the same
    # reason.
    for loop, into_hole in [(outer, False)] + [(h, True) for h in inners]:
        count = len(loop)
        for i in range(count):
            a, b = loop[i], loop[(i + 1) % count]
            du, dv = b[0] - a[0], b[1] - a[1]
            length = math.hypot(du, dv)
            if length < _EPS:
                continue
            pu, pv = dv / length, -du / length
            probe = ((a[0] + b[0]) * 0.5 + pu * _EPS,
                     (a[1] + b[1]) * 0.5 + pv * _EPS)
            if _point_in_polygon(probe, loop) != into_hole:
                pu, pv = -pu, -pv
            outward = _sub(to3d(pu, pv, 0.0), to3d(0.0, 0.0, 0.0))
            quad = [to3d(a[0], a[1], start), to3d(b[0], b[1], start),
                    to3d(b[0], b[1], end), to3d(a[0], a[1], end)]
            faces.append((_oriented(quad, outward), []))
    return faces


# ---- the moving panel -------------------------------------------------------
def _rect(x0, z0, x1, z1) -> list:
    """A rectangle in the elevation plane, wound so its normal faces -y."""
    return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]


def _rotate_faces(faces, pivot: tuple, angle: float) -> list:
    """Every point turned about the vertical hinge at ``pivot``, in (x, y).

    One helper for everything that opens — a door's leaf, its handle, a
    window's sash and the glass in it — because they are all the same shape: a
    profile in elevation, a depth, and a hinge down one side.
    """
    if abs(angle) < 1e-12:
        return faces
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    px, py = pivot

    def turn(point):
        dx, dy = point[0] - px, point[1] - py
        return (px + dx * cos_a - dy * sin_a,
                py + dx * sin_a + dy * cos_a,
                point[2])

    return [([turn(q) for q in loop], [[turn(q) for q in h] for h in holes])
            for loop, holes in faces]


def panel(outline, holes, y0: float, y1: float, pivot: tuple,
          angle: float) -> list:
    """A part that opens: its profile in elevation, its depth, turned by its
    hinge. ``holes`` is what makes a window's sash a frame rather than a slab.
    """
    return _rotate_faces(prism(outline, holes, y0, y1, plane="xz"), pivot, angle)


def frame_opening(p: dict) -> tuple[float, float, float, float]:
    """``(clear_width, clear_height, jamb, bottom)`` — the hole inside the
    frame, which is where the panel, the sash and the glass all live.

    A door has no bottom member, so its clear height runs from the floor; a
    window's kozijn does have one, which is what ``frame_b`` is.
    """
    clear_w = max(p["width"] - 2.0 * p["frame_w"], 0.0)
    clear_h = max(p["height"] - p["frame_h"] - p["frame_b"], 0.0)
    return clear_w, clear_h, p["frame_w"], p["frame_b"]


def hinge_and_panel(p: dict, depth: float) -> tuple[tuple, float, float, float]:
    """``(pivot, y0, thickness, y1)`` — where the moving part is, and where it
    turns.

    The part sits centred in the frame's depth, and its hinge axis runs through
    the middle of its thickness: a real hinge hangs on the panel's face, but a
    panel that pivots about its own centre line is the one whose swing symbol
    and whose open position agree.
    """
    hangs_left, _ = params_mod.leaf_direction(p)
    clear_w, _clear_h, jamb, _bottom = frame_opening(p)

    if params_mod.is_window(p):
        thickness = min(p["sash_d"], depth)
    else:
        thickness = min(p["leaf_t"], depth)
    y0 = max((depth - thickness) * 0.5, 0.0)
    pivot_x = jamb if hangs_left > 0 else jamb + clear_w
    return (pivot_x, y0 + thickness * 0.5), y0, thickness, y0 + thickness


# ---- the parts --------------------------------------------------------------
def parts(p: dict, wall_depth: float) -> dict:
    """Every part of the opening, as ``{name: [face, …]}``.

    ``Frame`` is the lining — the kozijn, a ring the section's depth into the
    wall; ``Leaf`` (a door) or ``Sash`` (an opening window) is what moves, with
    its ``Glass``; ``Threshold`` and ``Handle`` a door may add.

    The same names for both kinds, so the Parts tray, the pose reading and the
    tests do not care which one it is.
    """
    p = params_mod.normalize(p)
    depth = max(float(wall_depth), 0.02)
    held = params_mod.frame_depth(p, depth)
    clear_w, clear_h, jamb, bottom = frame_opening(p)
    angle = params_mod.swing_angle(p)
    pivot, y0, thickness, y1 = hinge_and_panel(p, held)
    hangs_left, _opens_away = params_mod.leaf_direction(p)

    out: dict = {}

    # The frame: the opening rectangle, less the clear hole, as deep as the
    # section. `frame_depth` of 0 follows the wall, which is what a door lining
    # does; a window or a door frame is its own 67 × 114 kozijn.
    outline = _rect(0.0, 0.0, p["width"], p["height"])
    inner = _rect(jamb, bottom, jamb + clear_w, bottom + clear_h)
    out["Frame"] = prism(outline, [inner], 0.0, held, plane="xz")

    panel_x0 = jamb if hangs_left > 0 else jamb + clear_w
    panel_x1 = panel_x0 + hangs_left * clear_w
    left, right = min(panel_x0, panel_x1), max(panel_x0, panel_x1)

    if params_mod.is_window(p):
        if thickness > 0.0:
            # The sash: a frame in elevation, 54 mm of face and 67 mm deep, so
            # its glass has somewhere to sit.
            inset = p["sash_w"]
            sash_inner = _rect(left + inset, bottom + inset,
                               right - inset, bottom + clear_h - inset)
            out["Sash"] = panel(_rect(left, bottom, right, bottom + clear_h),
                                [sash_inner], y0, y1, pivot, angle)
            glass = sash_inner
        else:
            glass = _rect(left, bottom, right, bottom + clear_h)
        if params_mod.glazed(p):
            half = min(p["glass_t"], thickness if thickness else held) * 0.5
            centre = (y0 + y1) * 0.5 if thickness else held * 0.5
            out["Glass"] = panel(glass, [], centre - half, centre + half,
                                 pivot, angle)
        return out

    # A door: the leaf is a slab of the clear opening, and the frame it hangs
    # in is the lining.
    if thickness > 0.0:
        out["Leaf"] = panel(_rect(left, bottom, right, bottom + clear_h), [],
                            y0, y1, pivot, angle)

        if p["handle"] > 0.0 and p["handle_len"] > 0.0:
            # A lever near the free edge, standing out of the face of the leaf
            # on the side the user is on, and turning with the leaf.
            free = panel_x0 + hangs_left * clear_w
            inward = -hangs_left
            hx0 = min(free + inward * 0.13, free + inward * 0.03)
            hx1 = max(free + inward * 0.13, free + inward * 0.03)
            out["Handle"] = panel(
                _rect(hx0, p["handle"] - 0.015, hx1, p["handle"] + 0.015), [],
                y0 - p["handle_len"], y0, pivot, angle)

    if p["threshold"] > 0.0:
        saddle = _rect(jamb, 0.0, jamb + clear_w, p["threshold"])
        out["Threshold"] = prism(saddle, [], 0.0, depth, plane="xz")
    return out


def swing_symbol(p: dict, wall_depth: float) -> list:
    """The swing arc as ``[(a, b), …]`` straight segments, at ``symbol_z``.

    The free edge of what opens, swept from closed to open: the convention
    every plan drawing uses, and the only part of an opening that is not a
    solid. It is kept out of the opening's own groups so that a layer can hide
    it — a nested group's layer is not consulted by the drawing pass, but a
    top-level group's is.
    """
    p = params_mod.normalize(p)
    if not p["symbol"] or not params_mod.moves(p):
        return []
    depth = max(float(wall_depth), 0.02)
    clear_w, _clear_h, _jamb, _bottom = frame_opening(p)
    if clear_w <= 0.0:
        return []
    hangs_left, _opens_away = params_mod.leaf_direction(p)
    pivot, _y0, _t, _y1 = hinge_and_panel(p, params_mod.frame_depth(p, depth))
    theta = params_mod.swing_angle(p)
    start = 0.0 if hangs_left > 0 else math.pi

    steps = max(_ARC_MIN_SEGMENTS,
                int(abs(math.radians(p["open_angle"])) /
                    math.radians(_ARC_STEP_DEG)) + 1)
    z = p["symbol_z"]
    points = []
    for i in range(steps + 1):
        phi = start + theta * (i / steps)
        points.append((pivot[0] + clear_w * math.cos(phi),
                       pivot[1] + clear_w * math.sin(phi), z))
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)]


def outline_symbol(p: dict, wall_depth: float) -> list:
    """The opening rectangle, drawn on the layer the arc is on.

    The other half of the plan symbol: without it the arc floats. Drawn at
    ``symbol_z`` like the arc, which is measured from the bottom of the
    opening — the floor for a door, the sill for a window.
    """
    p = params_mod.normalize(p)
    if not p["symbol"]:
        return []
    clear_w, _clear_h, jamb, _bottom = frame_opening(p)
    if clear_w <= 0.0:
        return []
    z = p["symbol_z"]
    return [(jamb, 0.0, z), (jamb + clear_w, 0.0, z),
            (jamb + clear_w, max(float(wall_depth), 0.02), z),
            (jamb, max(float(wall_depth), 0.02), z)]


# ---- what the tests, and the takeoff, want to know --------------------------
def volume(faces) -> float:
    """The signed volume enclosed by ``faces`` (positive when every face is
    wound outward — which is what tells a closed solid from a hole in one)."""
    total = 0.0
    for loop, holes in faces:
        for ring in [loop, *holes]:
            count = len(ring)
            for i in range(1, count - 1):
                total += _dot(ring[0], _cross(ring[i], ring[i + 1])) / 6.0
    return total


def bounds(faces) -> tuple:
    """``(min, max)`` over every point, for a sanity check on the layout."""
    points = [p for loop, holes in faces for ring in (loop, *holes)
              for p in ring]
    if not points:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    lows = tuple(min(p[i] for p in points) for i in range(3))
    highs = tuple(max(p[i] for p in points) for i in range(3))
    return lows, highs


def all_faces(built: dict) -> list:
    """Every face of every part, for a whole-door check."""
    return [face for faces in built.values() for face in faces]
