# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Putting an opening in a wall of ours: the association.

This is what the whole walls layer was for. When a door or window is placed on
one of **our** walls, nothing is cut: the opening is added to the wall's own
`openings` list, the wall regenerates with the hole, and the opening is placed
at that hole. From then on the two know about each other by id:

* change the window's size → the opening changes and the wall follows;
* erase the window → the opening goes and the wall closes up;
* move or re-skin the wall → both follow, because both come from parameters.

Contrast the freeform path in `opening.py`, which cuts faces: that is topology
surgery, and afterwards the wall is no longer anything in particular.

The frame is worked out from the wall itself, so a door's handedness reads from
the face that was clicked — the same semantics as a freeform placement, because
the opening object does not know or care which kind of wall it is in.
"""
from __future__ import annotations

import uuid

from PySide6.QtGui import QVector3D

from . import object as object_mod
from . import opening as opening_mod
from . import params as params_mod
from . import wall_object as wall_obj
from . import walls

#: How far inside a segment an opening is kept, so it never lands on a corner.
_EDGE = 0.02


def host_wall(scene, owner):
    """The wall of ours that ``owner`` is, or a skin of."""
    if owner is None:
        return None
    if wall_obj.is_wall(owner):
        return owner
    return None


def _nearest_segment(w: dict, click) -> tuple:
    """``(index, direction, distance along it, length)`` for the closest run."""
    path = w["path"]
    best = None
    for index, (a, b) in enumerate(zip(path, path[1:])):
        delta = (b[0] - a[0], b[1] - a[1])
        length = (delta[0] ** 2 + delta[1] ** 2) ** 0.5
        if length < 1e-9:
            continue
        direction = (delta[0] / length, delta[1] / length)
        along = (click.x() - a[0]) * direction[0] + \
            (click.y() - a[1]) * direction[1]
        along = min(max(along, 0.0), length)
        foot = (a[0] + direction[0] * along, a[1] + direction[1] * along)
        away = ((click.x() - foot[0]) ** 2 + (click.y() - foot[1]) ** 2) ** 0.5
        if best is None or away < best[2][2] - 1e-9:
            best = (index, (a, direction), (along, away, 0.0), length)
    if best is None:
        raise opening_mod.OpeningError("That wall has no direction to put a "
                                       "door in.")
    index, (_start, direction), (along, _away, _z), length = best
    return index, direction, along, length


def placement(wall, click, normal: QVector3D, p: dict) -> dict:
    """Where an opening goes in ``wall``, and the frame the door sits in.

    ``(frame, opening, depth)`` — the opening as data, the door's own frame, and
    how deep the wall is through it.
    """
    w = wall_obj.wall_params(wall)
    if len(w["path"]) < 2:
        raise opening_mod.OpeningError("That wall has no length yet.")

    index, direction, along, length = _nearest_segment(w, click)
    width = min(p["width"], max(length - 2 * _EDGE, 0.2))
    start = min(max(along - width * 0.5, _EDGE),
                max(length - width - _EDGE, _EDGE))
    opening = {
        "id": uuid.uuid4().hex[:12],
        "segment": index,
        "start": start,
        "width": width,
        "height": p["height"],
        "sill": p["sill"],
    }

    # The frame: x along the wall towards the viewer's right, y into the wall
    # away from the face that was clicked, z up — exactly the frame a freeform
    # opening uses, so handing means the same thing either way.
    across, into, up = opening_mod.axes(_FaceLike(normal))
    depth = walls.total_thickness(w)
    # The clicked face is half the wall's thickness out along its own normal.
    origin = (w["path"][index][0] + direction[0] * start
              + normal.x() * depth * 0.5,
              w["path"][index][1] + direction[1] * start
              + normal.y() * depth * 0.5,
              w["base"] + p["sill"])
    del across
    frame = {"origin": origin,
             "x": opening_mod.as_tuple(_right(normal)),
             "y": opening_mod.as_tuple(into),
             "z": opening_mod.as_tuple(up)}
    return frame, opening, depth


class _FaceLike:
    """The little a face has to offer ``opening.axes``: a normal."""

    def __init__(self, normal: QVector3D) -> None:
        self._normal = normal

    def normal(self) -> QVector3D:
        return self._normal


def _right(normal: QVector3D) -> QVector3D:
    """The viewer's right, looking at the face that has this normal."""
    up = QVector3D(0.0, 0.0, 1.0)
    if abs(normal.normalized().z()) > 0.9:
        up = QVector3D(0.0, 1.0, 0.0)
    right = QVector3D.crossProduct(up, normal.normalized())
    if right.length() < 1e-9:
        raise opening_mod.OpeningError("That face has no direction along it.")
    right.normalize()
    return right


def add(scene, wall, click, normal: QVector3D, p: dict, viewport=None):
    """Add an opening to ``wall`` and stand a door or window in it."""
    p = params_mod.normalize(p)
    problems = params_mod.validate(p)
    if problems:
        raise opening_mod.OpeningError(problems[0])

    frame, opening, depth = placement(wall, click, normal, p)
    w = wall_obj.wall_params(wall)
    w["openings"] = [item for item in w["openings"]
                     if item.get("id") != opening["id"]]
    w["openings"].append(opening)
    wall_obj.regenerate(scene, wall, w)

    item = object_mod.create(scene, None, None, p, viewport=viewport,
                             placement={"frame": frame, "depth": depth,
                                        "opening": opening["id"],
                                        "wall": wall.uid})
    return item


def opening_of(scene, item):
    """``(wall, opening)`` for a door or window hosted in one of our walls."""
    data = object_mod.data_of(item) or {}
    host = data.get("host") or {}
    uid = host.get("wall")
    if not uid:
        return None, None
    wall = next((g for g in scene.groups
                 if getattr(g, "uid", None) == uid), None)
    if wall is None:
        return None, None
    wanted = host.get("opening")
    for opening in wall_obj.wall_params(wall)["openings"]:
        if opening.get("id") == wanted:
            return wall, opening
    return wall, None


def resize(scene, item, p: dict) -> bool:
    """The window changed: grow or shrink its opening and rebuild the wall.

    The association, in one function: both the wall and the door are rewritten
    inside the caller's single undo step.
    """
    wall, opening = opening_of(scene, item)
    if wall is None or opening is None:
        return False
    w = wall_obj.wall_params(wall)
    changed = False
    for item_opening in w["openings"]:
        if item_opening.get("id") != opening["id"]:
            continue
        for key in ("width", "height", "sill"):
            if abs(float(item_opening.get(key, 0.0)) - float(p[key])) > 1e-9:
                item_opening[key] = float(p[key])
                changed = True
    if changed:
        wall_obj.regenerate(scene, wall, w)
    return changed


def remove(scene, item) -> bool:
    """The window is going: take its opening out and close the wall."""
    wall, opening = opening_of(scene, item)
    if wall is None or opening is None:
        return False
    w = wall_obj.wall_params(wall)
    w["openings"] = [entry for entry in w["openings"]
                     if entry.get("id") != opening["id"]]
    wall_obj.regenerate(scene, wall, w)
    return True
