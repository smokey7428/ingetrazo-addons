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


# ---- the leaf's hinge -------------------------------------------------------
def _rotate(point, pivot, angle: float):
    """``point`` turned about ``pivot`` in the (x, y) plane."""
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    dx, dy = point[0] - pivot[0], point[1] - pivot[1]
    return (pivot[0] + dx * cos_a - dy * sin_a,
            pivot[1] + dx * sin_a + dy * cos_a)


def _rect(x0, y0, x1, y1, pivot=None, angle: float = 0.0):
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if pivot is None or not corners:
        return corners
    return [_rotate(c, pivot, angle) for c in corners]


def frame_opening(p: dict) -> tuple[float, float, float, float]:
    """``(clear_width, clear_height, jamb_x, head_z)`` — the hole the leaf sits
    in, inside the lining. A door has no lining along the floor, so the clear
    height is measured from the floor."""
    clear_w = max(p["width"] - 2.0 * p["frame_w"], 0.0)
    clear_h = max(p["height"] - p["frame_h"], 0.0)
    return clear_w, clear_h, p["frame_w"], p["frame_h"]


def hinge_and_leaf(p: dict, wall_depth: float) -> tuple[tuple, float, float]:
    """``(pivot, leaf_thickness, leaf_centre_y)`` — where the leaf turns.

    The leaf sits centred in the opening, so its hinge axis runs through the
    middle of its thickness: a real hinge hangs on the leaf's face, but a door
    that pivots about its own centre line is the one whose swing symbol and
    whose open leaf agree.
    """
    hangs_left, _ = params_mod.leaf_direction(p)
    clear_w, _clear_h, jamb, _head = frame_opening(p)
    pivot_x = jamb if hangs_left > 0 else jamb + clear_w
    thickness = min(p["leaf_t"], max(float(wall_depth), 0.02))
    centre_y = max(float(wall_depth), 0.02) * 0.5
    return (pivot_x, centre_y), thickness, centre_y


# ---- the parts --------------------------------------------------------------
def parts(p: dict, wall_depth: float) -> dict:
    """Every part of the door, as ``{name: [face, …]}``.

    ``Frame`` — the lining through the opening, a ring the full depth of the
    wall; ``Leaf`` — the leaf standing open at ``open_angle``; ``Threshold`` —
    a saddle across the opening, when asked for; ``Handle`` — a lever on the
    leaf, turning with it.
    """
    p = params_mod.normalize(p)
    depth = max(float(wall_depth), 0.02)
    clear_w, clear_h, jamb, head = frame_opening(p)
    hangs_left, _opens_away = params_mod.leaf_direction(p)
    angle = params_mod.swing_angle(p)
    pivot, thickness, centre_y = hinge_and_leaf(p, depth)

    out: dict = {}

    # The lining: the opening rectangle, less the clear hole, through the wall.
    # No member along the floor — that is a threshold, not part of the frame —
    # so the clear height is measured from the floor to under the head lining.
    outline = [(0.0, 0.0), (p["width"], 0.0),
               (p["width"], p["height"]), (0.0, p["height"])]
    inner = [(jamb, 0.0), (jamb + clear_w, 0.0),
             (jamb + clear_w, clear_h), (jamb, clear_h)]
    out["Frame"] = prism(outline, [inner], 0.0, depth, plane="xz")

    # The leaf, standing open: its cross-section turned about the hinge, then
    # raised from the floor to under the head lining.
    leaf_x = jamb if hangs_left > 0 else jamb + clear_w
    leaf_far = leaf_x + hangs_left * clear_w
    leaf_rect = _rect(min(leaf_x, leaf_far), centre_y - thickness * 0.5,
                      max(leaf_x, leaf_far), centre_y + thickness * 0.5,
                      pivot=pivot, angle=angle)
    out["Leaf"] = prism(leaf_rect, [], 0.0, clear_h, plane="xy")

    if p["threshold"] > 0.0:
        saddle = [(jamb, 0.0), (jamb + clear_w, 0.0),
                  (jamb + clear_w, depth), (jamb, depth)]
        out["Threshold"] = prism(saddle, [], 0.0, p["threshold"], plane="xy")

    if p["handle"] > 0.0:
        # A lever near the free edge, standing out of the face of the leaf the
        # user is on, and turning with the leaf.
        free = leaf_x + hangs_left * clear_w
        inward = -hangs_left                      # back from the free edge
        x0 = min(free + inward * 0.13, free + inward * 0.03)
        x1 = max(free + inward * 0.13, free + inward * 0.03)
        face_y = centre_y - thickness * 0.5
        lever = _rect(x0, face_y - p["handle_len"], x1, face_y,
                      pivot=pivot, angle=angle)
        out["Handle"] = prism(lever, [], p["handle"] - 0.015,
                              p["handle"] + 0.015, plane="xy")
    return out


def swing_symbol(p: dict, wall_depth: float) -> list:
    """The swing arc as ``[(a, b), …]`` straight segments, at ``symbol_z``.

    The leaf's free edge, swept from closed to open: the convention every plan
    drawing uses, and the only part of a door that is not a solid. It is kept
    out of the door's own groups so that a layer can hide it — a nested group's
    layer is not consulted by the drawing pass, but a top-level group's is.
    """
    p = params_mod.normalize(p)
    if not p["symbol"]:
        return []
    depth = max(float(wall_depth), 0.02)
    clear_w, _clear_h, _jamb, _head = frame_opening(p)
    if clear_w <= 0.0:
        return []
    hangs_left, _opens_away = params_mod.leaf_direction(p)
    pivot, _thickness, _centre_y = hinge_and_leaf(p, depth)
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
    """The door's opening rectangle on the floor, as one closed loop.

    The other half of the plan symbol: without it the arc floats. Drawn at
    ``symbol_z`` like the arc, and on the same layer.
    """
    p = params_mod.normalize(p)
    if not p["symbol"]:
        return []
    clear_w, _clear_h, jamb, _head = frame_opening(p)
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
