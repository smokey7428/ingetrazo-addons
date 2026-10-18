# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""A wall's geometry: skins swept along a path, mitred where it turns.

Every skin is built as **one closed solid per segment** — the skin's plan
quadrilateral, extruded vertically. That shape is what makes mitres free: a
corner is simply a corner of the plan polygon, so two segments meeting at any
angle join on the mitre line with no overlap and no gap, and each skin stays a
solid of its own with a real volume.

The mitre is the standard construction: at a vertex, the corner of a skin at
offset ``o`` is where the two segments' offset lines cross. Offsets are measured
from the **path**, which is the wall's centre line, so the skins sit half on
either side of what was drawn.

No booleans, no topology surgery: the wall is generated from its numbers every
time, which is the whole point of owning it.

Pure tuples, so the whole of it is testable without Qt or a scene.
"""
from __future__ import annotations

import math

from . import geometry
from . import walls

#: Two directions closer than this (in cross product) are the same direction.
_PARALLEL = 1e-9

#: Below this angle between two segments a mitre needs more room than a wall
#: has; the joint falls back to square ends instead of turning itself inside out.
_MIN_JOINT_DEG = 12.0


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _cross(a, b) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _unit(v):
    length = math.hypot(v[0], v[1])
    if length < 1e-12:
        return (0.0, 0.0)
    return (v[0] / length, v[1] / length)


def _perp(d):
    """The left normal of a plan direction."""
    return (-d[1], d[0])


def frames(w: dict) -> list:
    """``[(start, end, direction, normal, length), …]`` — one per segment."""
    path = w["path"]
    out = []
    for a, b in zip(path, path[1:]):
        delta = _sub(b, a)
        length = math.hypot(delta[0], delta[1])
        if length < 1e-9:
            continue                       # a duplicated point: not a segment
        direction = _unit(delta)
        out.append((tuple(a), tuple(b), direction, _perp(direction), length))
    return out


def joint_ok(w: dict, index: int) -> bool:
    """Whether the joint at vertex ``index`` can be mitred.

    A very acute corner needs a mitre longer than the wall is thick, and a wall
    built that way turns itself inside out. Rather than emit nonsense, the
    joint is squared off and the caller may say so.
    """
    path, count = w["path"], len(w["path"])
    if index <= 0 or index >= count - 1:
        return False                       # an end: always square
    before, after = _unit(_sub(path[index], path[index - 1])), \
        _unit(_sub(path[index + 1], path[index]))
    if abs(_cross(before, after)) < _PARALLEL:
        return False                       # straight through: no joint
    angle = math.degrees(math.acos(max(-1.0, min(1.0, _dot(before, after)))))
    if 180.0 - angle < _MIN_JOINT_DEG:
        return False
    # And the segments have to be long enough to hold the mitre.
    reach = walls.total_thickness(w) / max(math.sin(math.radians(angle)), 0.05)
    return _segment_length(path, index - 1) > reach and \
        _segment_length(path, index) > reach


def _segment_length(path, index: int) -> float:
    a, b = path[index], path[index + 1]
    return math.hypot(b[0] - a[0], b[1] - a[1])


def corner(w: dict, vertex: int, offset: float, incoming: bool = False) -> tuple:
    """The plan corner of the skin at ``offset`` at ``vertex``.

    At a mitred joint it is where the two offset lines cross — the same point
    whichever segment asks, which is what makes the two runs one solid. At the
    path's ends, and at a joint too sharp to mitre, it is the point square
    across **that segment**: the runs then butt and overlap slightly rather
    than sharing a face, so each stays a closed solid on its own. ``incoming``
    says whether the segment arriving at the vertex is the one asking.
    """
    path = w["path"]
    count = len(path)
    if 0 < vertex < count - 1 and joint_ok(w, vertex):
        return _mitre(w, vertex, offset)

    index = min(max(vertex - 1 if incoming else vertex, 0), count - 2)
    start, end = path[index], path[index + 1]
    normal = _perp(_unit(_sub(end, start)))
    point = path[vertex]
    return (point[0] + normal[0] * offset, point[1] + normal[1] * offset)


def _mitre(w: dict, vertex: int, offset: float) -> tuple:
    """Where the two segments' offset lines cross at a mitred joint."""
    path = w["path"]
    point = path[vertex]
    in_dir = _unit(_sub(path[vertex], path[vertex - 1]))
    out_dir = _unit(_sub(path[vertex + 1], path[vertex]))
    in_normal, out_normal = _perp(in_dir), _perp(out_dir)

    # Where  point + o·in_normal + a·in_dir  meets  point + o·out_normal + b·out_dir
    right = (offset * (out_normal[0] - in_normal[0]),
             offset * (out_normal[1] - in_normal[1]))
    determinant = -_cross(in_dir, out_dir)
    a = (right[0] * -out_dir[1] - -out_dir[0] * right[1]) / determinant
    return (point[0] + offset * in_normal[0] + a * in_dir[0],
            point[1] + offset * in_normal[1] + a * in_dir[1])


def plan_quad(w: dict, vertex: int, offset0: float,
              offset1: float) -> list:
    """One skin's plan quadrilateral between two vertices."""
    return [corner(w, vertex, offset0), corner(w, vertex, offset1),
            corner(w, vertex + 1, offset1), corner(w, vertex + 1, offset0)]


def _area(quad) -> float:
    total = 0.0
    count = len(quad)
    for i in range(count):
        a, b = quad[i], quad[(i + 1) % count]
        total += a[0] * b[1] - b[0] * a[1]
    return abs(total) * 0.5


def runs(w: dict) -> list:
    """``[(first vertex, last vertex), …]`` — the stretches that mitre as one.

    A mitre joins two segments into **one** solid: two prisms that merely share
    the mitre face would leave that face inside the wall, every edge along it
    bordering four faces instead of two, and ``core/bim.py`` would then refuse
    to report a volume at all. So a run of mitred segments is built as a single
    extruded band — one outline, one solid.

    A joint that had to be squared off (see :func:`joint_ok`) starts a new run
    instead, because two squared-off segments overlap and cannot be one simple
    outline.
    """
    count = len(w["path"])
    out, start = [], 0
    for vertex in range(1, count - 1):
        if not joint_ok(w, vertex):
            out.append((start, vertex))
            start = vertex
    out.append((start, count - 1))
    return out


def band_outline(w: dict, first: int, last: int,
                 offset0: float, offset1: float) -> list:
    """One skin's plan outline over a run: along one side, back along the other."""
    def side(offset: float) -> list:
        out = [corner(w, first, offset, incoming=False)]
        out += [corner(w, vertex, offset)
                for vertex in range(first + 1, last)]
        out += [corner(w, last, offset, incoming=True)]
        return out

    return side(offset0) + list(reversed(side(offset1)))


def _station(w: dict, boundary: tuple, offset: float) -> tuple:
    """The plan point of a piece boundary at ``offset``.

    A boundary is either a vertex of the path — where the band turns, on its
    mitre — or a station part-way along a segment, where an opening begins.
    """
    if boundary[0] == "vertex":
        _tag, vertex, incoming = boundary
        return corner(w, vertex, offset, incoming=incoming)
    _tag, segment, distance = boundary
    path = w["path"]
    start, end = path[segment], path[segment + 1]
    direction = _unit(_sub(end, start))
    normal = _perp(direction)
    return (start[0] + normal[0] * offset + direction[0] * distance,
            start[1] + normal[1] * offset + direction[1] * distance)


def _order(w: dict, boundary: tuple) -> float:
    """Where a boundary sits along the path, in whole segments.

    Monotonic, which is the whole point: a vertex is the start of its segment,
    and a station is that segment plus how far along it the station is. Only
    ever compared with another boundary's order — never with a distance.
    """
    if boundary[0] == "vertex":
        return float(boundary[1])
    _tag, segment, distance = boundary
    path = w["path"]
    length = math.hypot(path[segment + 1][0] - path[segment][0],
                        path[segment + 1][1] - path[segment][1])
    return float(segment) + distance / max(length, 1e-9)


def band_between(w: dict, offset0: float, offset1: float,
                 first: tuple, last: tuple) -> list:
    """One skin's plan outline between two boundaries: out along one side,
    back along the other, turning on the mitre at any vertex in between."""
    low, high = _order(w, first), _order(w, last)

    def side(offset: float) -> list:
        out = [_station(w, first, offset)]
        for vertex in range(1, len(w["path"]) - 1):
            if low + 1e-9 < float(vertex) < high - 1e-6:
                out.append(corner(w, vertex, offset))
        out.append(_station(w, last, offset))
        return out

    return side(offset0) + list(reversed(side(offset1)))


def _extrude(w: dict, offset0: float, offset1: float,
             first: tuple, last: tuple, low: float, high: float) -> list:
    outline = band_between(w, offset0, offset1, first, last)
    if len(outline) < 3 or _area(outline) < 1e-9:
        return []
    return geometry.prism(outline, [], low, high, plane="xy")


def skin_faces(w: dict) -> dict:
    """``{skin name: [face, …]}`` — the whole wall, one solid per run per skin.

    An **opening** splits its run into pieces: the wall either side of it, and
    what is left above and below it. Each piece is a closed solid of its own,
    which is what keeps a wall with a hole in it measurable — two solids that
    merely *shared* a face would leave that face inside the wall and every edge
    along it bordering four faces, and ``core/bim.py`` would report no volume
    at all.

    One part per skin, so the Parts tray reads like the build-up does:
    Buitenblad, Isolatie, Binnenblad, each with its own material and its own
    volume.
    """
    w = walls.normalize(w)
    if len(w["path"]) < 2 or not w["skins"]:
        return {}
    base, height = w["base"], w["height"]
    top = base + height
    stretches = runs(w)
    out: dict = {}

    for skin, offset0, offset1 in walls.offsets(w):
        faces: list = []
        for first, last in stretches:
            if last <= first:
                continue
            hosted = [opening for opening in w["openings"]
                      if first <= opening["segment"] < last]
            hosted.sort(key=lambda item: (item["segment"], item["start"]))

            cursor = ("vertex", first, False)
            for opening in hosted:
                start = ("at", opening["segment"], opening["start"])
                end = ("at", opening["segment"],
                       opening["start"] + opening["width"])
                if _order(w, start) <= _order(w, cursor) + 1e-6:
                    continue                    # already past it: skip
                faces += _extrude(w, offset0, offset1, cursor, start,
                                  base, top)

                sill = base + opening["sill"]
                head = sill + opening["height"]
                if sill > base + 1e-6:
                    faces += _extrude(w, offset0, offset1, start, end,
                                      base, sill)
                if head < top - 1e-6:
                    faces += _extrude(w, offset0, offset1, start, end,
                                      head, top)
                cursor = end

            end_boundary = ("vertex", last, True)
            if _order(w, end_boundary) > _order(w, cursor) + 1e-6:
                faces += _extrude(w, offset0, offset1, cursor, end_boundary,
                                  base, top)
        if faces:
            out[skin["name"]] = faces
    return out


def bounds(built: dict) -> tuple:
    """``(min, max)`` over the whole wall, for a sanity check on the layout."""
    faces = [face for group in built.values() for face in group]
    return geometry.bounds(faces)


def volume(built: dict) -> float:
    """The wall's volume, over every skin — what a take-off would report."""
    faces = [face for group in built.values() for face in group]
    return geometry.volume(faces)
