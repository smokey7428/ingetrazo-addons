# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Opening a wall for a door, and putting the wall back.

The pattern is Windowizer's, and it is the whole reason a hosted opening works
at all in a freeform modeller:

1. the host face — the bit of wall the door is cut into — is **removed**;
2. the four reveal surfaces are added, each carrying **the host's own attrs**,
   so the wall keeps its material, its layer and its BIM tag through the
   reveal and stays one object;
3. a matching **hole is punched in the far face**, so the wall is still a
   closed solid and its volume is still reported honestly;
4. the removed face's loop, attrs and the new hole are recorded, so
   :func:`close` can put the wall back exactly as it was.

No destructive booleans: the wall's own faces are edited, and undoing is a
matter of restoring the mesh (see ``object.py``).

**One limitation, inherited deliberately:** the opening is *topology*, not an
association. If the wall is edited afterwards the reveals may no longer line
up, and :func:`close` then refuses rather than restore a face that would
double up geometry. Windowizer says the same in its own words — "the wall has
been edited since, so the opening was not closed for: {name}. Close it by
hand."

Nothing here touches Qt widgets, so the arithmetic — the frame, where the
opening goes, the reveal quads — is all testable with plain vectors.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from . import geometry

#: How thick a wall we will cut through. Past this we refuse instead of boring
#: a tunnel: a building drawn as one massing box has its far facade behind
#: every face, and a door is not a tunnel.
WALL_MAX = 0.80

#: How far off parallel two faces may be and still be one wall's two sides.
_PARALLEL = 0.99

#: How far from vertical a face has to be before we call it a floor.
_UPRIGHT = 0.9

#: Two points closer than this are the same point (metres).
_EPS = 1e-5


class OpeningError(Exception):
    """The wall cannot take this opening, said in words a user can act on."""


def as_tuple(v) -> tuple:
    """A point as a plain tuple — for signatures and for the geometry module,
    which works in tuples so that it needs no Qt."""
    return (v.x(), v.y(), v.z())


# ---- the frame the door lives in -------------------------------------------
def axes(face) -> tuple:
    """``(X, Y, Z)`` for building on ``face`` — right-handed, world metres.

    ``Y`` runs **into** the wall, away from the face that was clicked; ``Z`` is
    up; ``X`` runs along the wall towards the viewer's **right**, so "left
    hand" is the left of the person looking at the wall — the reading every
    drawing and every door schedule uses.
    """
    normal = face.normal().normalized()
    world_up = QVector3D(0.0, 0.0, 1.0)
    if abs(normal.z()) > _UPRIGHT:            # a floor or a ceiling, not a wall
        world_up = QVector3D(0.0, 1.0, 0.0)
    across = QVector3D.crossProduct(world_up, normal)
    if across.length() < 1e-9:
        raise OpeningError("That face has no direction along it to put a door.")
    across.normalize()
    into = -normal
    up = QVector3D.crossProduct(across, into).normalized()
    return across, into, up


def _extents(face, across: QVector3D, up: QVector3D) -> tuple:
    """The face's own box in ``(across, up)``, measured from the world origin.

    The origin cancels out of every use: an offset along ``across`` is the
    same wherever it is measured from.
    """
    us = [QVector3D.dotProduct(v.position, across) for v in face.loop]
    vs = [QVector3D.dotProduct(v.position, up) for v in face.loop]
    return min(us), max(us), min(vs), max(vs)


def at(face, across: QVector3D, up: QVector3D, u: float, v: float) -> QVector3D:
    """The point on the face's plane at ``(u, v)``.

    Measured from a corner of the face rather than from the world origin: a
    corner is certainly on the plane, and the plane is what matters.
    """
    anchor = face.loop[0].position
    return (anchor
            + across * (u - QVector3D.dotProduct(anchor, across))
            + up * (v - QVector3D.dotProduct(anchor, up)))


# ---- the far side of the wall ----------------------------------------------
def back_face(scene, face, depth_limit: float = WALL_MAX):
    """The face on the wall's far side and how far behind it lies, or ``None``.

    A candidate has to face the other way, be no further than ``depth_limit``,
    and have every corner of the host face land inside it once the host slides
    straight back — otherwise a wall behind a wall would be taken for the back
    of this one.
    """
    normal = face.normal().normalized()
    host = face.centroid()
    best = None
    for other in scene.mesh.faces:
        if other is face:
            continue
        if QVector3D.dotProduct(other.normal().normalized(), normal) > -_PARALLEL:
            continue                        # not the other side of a wall
        depth = -QVector3D.dotProduct(normal, other.centroid() - host)
        if depth <= _EPS or depth > depth_limit:
            continue
        if not _within(other, [v.position - normal * depth for v in face.loop]):
            continue
        if best is None or depth < best[1]:
            best = (other, depth)
    return best


def _within(face, points) -> bool:
    """Whether every point projects inside the face's ``(across, up)`` box.

    A box test on purpose: the far face of a wall is a rectangle in practice,
    and a point-in-polygon test would refuse the case we most want — cutting
    beside a hole the far face already has.
    """
    if face.normal().length() < 1e-9:
        return False
    across, _into, up = axes(face)
    u0, u1, v0, v1 = _extents(face, across, up)
    for point in points:
        u = QVector3D.dotProduct(point, across)
        v = QVector3D.dotProduct(point, up)
        if not (u0 - 1e-4 <= u <= u1 + 1e-4 and v0 - 1e-4 <= v <= v1 + 1e-4):
            return False
    return True


# ---- where the opening goes ------------------------------------------------
def plan(scene, face, click: QVector3D, p: dict):
    """``(origin, X, Y, Z, depth, corners)`` — decided, nothing touched yet.

    The opening stands on the bottom of the wall face it is cut into (the
    floor, for a wall standing on the floor) and is centred where the user
    clicked along it, slid inside the face rather than hanging off a jamb.

    Deciding before cutting is the point: the caller finds out that a door
    will not fit while the document is still intact.
    """
    across, into, up = axes(face)
    min_u, max_u, min_v, max_v = _extents(face, across, up)

    width, height = p["width"], p["height"]
    room = max_u - min_u
    if width > room + _EPS:
        raise OpeningError(
            f"The door is wider than the wall face it would be cut into "
            f"({width:.2f} m against {room:.2f} m). Pick a wider face, or make "
            f"the door narrower.")
    if height > max_v - min_v + _EPS:
        raise OpeningError(
            f"The door is taller than the wall it would be cut into "
            f"({height:.2f} m against {max_v - min_v:.2f} m).")

    left = QVector3D.dotProduct(click, across) - width * 0.5
    left = min(max(left, min_u), max_u - width)
    base = min_v

    origin = at(face, across, up, left, base)
    corners = [origin,
               origin + across * width,
               origin + across * width + up * height,
               origin + up * height]

    found = back_face(scene, face)
    if found is None:
        raise OpeningError(
            f"There is no wall behind that face within {WALL_MAX * 100:.0f} cm, "
            f"so there is nothing to cut through. Draw the wall as a solid — a "
            f"box, or push/pull the face — and try again.")
    return origin, across, into, up, found[1], corners


def reveal_quads(corners, offset, across: QVector3D, into: QVector3D,
                 up: QVector3D) -> list:
    """The four reveal surfaces, as ``[(loop, inward), …]``.

    One per side of the opening, running from the clicked face to the far one,
    each facing **into** the opening: the void is the material's new surface,
    and a reveal turned the wrong way would read as a lid over the door.
    """
    inward = {"bottom": up, "top": -up, "left": across, "right": -across}
    order = ((0, 1, "bottom"), (1, 2, "right"), (2, 3, "top"), (3, 0, "left"))
    quads = []
    for a, b, side in order:
        front_a, front_b = corners[a], corners[b]
        quad = [front_a, front_b, front_b + offset, front_a + offset]
        quads.append((geometry.oriented([as_tuple(q) for q in quad],
                                        as_tuple(inward[side])),
                      inward[side]))
    return quads


# ---- cutting, and putting it back ------------------------------------------
def cut(scene, face, corners, depth: float) -> dict:
    """Open the wall. Returns the record :func:`close` needs.

    The host face is **not** removed — a hole is punched in it, and one in the
    far face, with the four reveals joining the two rims. That is the one
    place this differs from Windowizer, and deliberately: Windowizer removes
    the face you select, which only closes up because you first draw a
    rectangle on the wall so the wall's own face already has a hole in it.
    Punching the hole instead means a door can be cut straight into the wall's
    face, and the wall stays a closed solid — every edge of it still borders
    exactly two faces, which is what the take-off needs before it will report
    a volume.
    """
    found = back_face(scene, face)
    if found is None:
        raise OpeningError("The wall's far side is gone — nothing was changed.")
    far, measured = found
    depth = measured if depth is None else min(depth, measured)

    mesh = scene.mesh
    host_attrs = dict(face.attrs or {})
    across, into, up = axes(face)
    offset = into * depth
    landed = [q + offset for q in corners]

    # The two holes first: if either cannot be made, nothing has been changed.
    front_loop = mesh.add_hole(face, list(reversed(corners)))
    back_loop = mesh.add_hole(far, landed)
    record = {
        "hole": {"front": [as_tuple(v.position) for v in front_loop],
                 "back": [as_tuple(v.position) for v in back_loop]},
        "reveals": [], "depth": depth,
        "host": {"attrs": host_attrs},
    }

    for loop, _inward in reveal_quads(corners, offset, across, into, up):
        added = mesh.add_face([QVector3D(*q) for q in loop])
        # The host's attrs, so the reveal keeps the wall's material, its layer
        # and its BIM tag, and the wall stays one object.
        added.attrs = dict(host_attrs)
        record["reveals"].append(signature(loop))
    return record


def signature(loop) -> str:
    """A cheap, stable fingerprint of a loop's corner positions.

    The mesh welds vertices, so a reveal face found again after an undo is not
    the same Python object — but its corners are in the same places, and that
    is what we match on.
    """
    return "|".join(",".join(f"{float(c):.6f}" for c in q) for q in loop)


def hole_of(face, points) -> list | None:
    """The hole loop of ``face`` whose corners are ``points``, or ``None``.

    How a far face is found again after a save or an undo: by the hole that
    was punched in it, which is the only thing that has to still be there.
    """
    wanted = _corners(points)
    for hole in face.hole_loops:
        if _corners([v.position for v in hole]) == wanted:
            return hole
    return None


def far_face(scene, points):
    """The face carrying a hole at exactly ``points``, or ``None``."""
    for face in scene.mesh.faces:
        if hole_of(face, points) is not None:
            return face
    return None


def _corners(points) -> frozenset:
    """The points as a comparable set, rounded past welding precision."""
    out = []
    for point in points:
        q = as_tuple(point) if hasattr(point, "x") else point
        out.append((round(float(q[0]), 6), round(float(q[1]), 6),
                    round(float(q[2]), 6)))
    return frozenset(out)


def close(scene, record: dict) -> bool:
    """Put the wall back: take the reveals out and fill both holes.

    False when the wall has been edited since — a reveal is missing, or a hole
    is gone. Nothing is changed in that case: this is the point at which a
    wrong guess would leave the wall with geometry it never had, so it is
    better to report than to repair.
    """
    mesh = scene.mesh
    if not record:
        return False

    wanted = list(record.get("reveals") or ())
    found = [f for f in mesh.faces
             if signature([as_tuple(v.position) for v in f.loop]) in wanted]
    if len(found) != len(wanted):
        return False

    holes = record.get("hole") or {}
    rims = []
    for side in ("front", "back"):
        points = holes.get(side) or []
        if not points:
            return False
        target = far_face(scene, points)
        loop = hole_of(target, points) if target is not None else None
        if loop is None:
            return False
        rims.append((target, loop))

    for face in found:
        mesh.remove_face(face)
    for target, loop in rims:
        mesh.remove_hole(target, loop)
    return True
