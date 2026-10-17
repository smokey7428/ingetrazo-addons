# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The door as a document object: make one, change it, erase it.

A door is **one container group**, tagged ``IfcDoor``, whose parts are nested
groups — the lining, the leaf, the threshold, the handle — all placed by one
matrix held in the parts' ``xform``, exactly as Windowizer places a window and
3D text places its letters. That is what makes it parametric: ``group.ext``
keeps the parameters and the frame, so the parameters travel with a copy,
survive save and open, and **Edit door** rebuilds the parts from new
parameters *where the door stands now*.

Its swing symbol is a **second, top-level group** of its own, on the symbol
layer. It has to be separate: the drawing pass and the hidden-line pass ask
only a *top-level* group which layer it is on (``world_mesh`` folds nested
children in without consulting them), so a symbol inside the door could never
be hidden in a 3D view and shown in a plan.

Everything that changes the document goes through :class:`DoorCommand`, which
captures the loose mesh, the groups, the plugin data, the materials and the
layers — so one user action is **one undo step**, and undo restores all of it.
"""
from __future__ import annotations

import copy
import logging

from PySide6.QtGui import QMatrix4x4, QVector3D, QVector4D

from core.group import Group
from core.history import Command
from core.mesh import Mesh

from . import geometry
from . import opening as opening_mod
from . import params as params_mod

log = logging.getLogger("ingetrazo.plugins.openings")

#: What a swing symbol's group is called — the Browser and the outliner read
#: it, and so do we when one has to be found again.
SYMBOL_NAME = "Swing symbol"

#: Where the openings' own bookkeeping lives in the document: one record each
#: keyed by its container's uid — the opening to close, and its symbol group.
def registry(scene) -> dict:
    """The doors' bookkeeping — read only. Write it with
    :func:`_write_registry`, which also takes the key away when it empties."""
    data = (getattr(scene, "plugin_data", None) or {}).get(params_mod.KEY)
    doors = data.get("doors") if isinstance(data, dict) else None
    return doors if isinstance(doors, dict) else {}


def _write_registry(scene, doors: dict) -> None:
    """Store the bookkeeping, or take the key away when there is none left.

    An empty ``{}`` under our key is not the same as no key at all: the core
    asks whether ``scene.plugin_data`` is empty to decide whether a document
    has anything in it.
    """
    if doors:
        scene.plugin_data[params_mod.KEY] = {"doors": doors}
    else:
        scene.plugin_data.pop(params_mod.KEY, None)


# ---- reading a door ---------------------------------------------------------
def data_of(group) -> dict | None:
    """The opening's own record on ``group``, or ``None`` if it is not one."""
    ext = getattr(group, "ext", None) or {}
    found = ext.get(params_mod.KEY) if isinstance(ext, dict) else None
    return found if isinstance(found, dict) else None


def is_opening(group) -> bool:
    return data_of(group) is not None


def opening_params(group) -> dict:
    """The door's parameters, normalised — never the raw stored dict."""
    return params_mod.normalize((data_of(group) or {}).get("params"))


def symbol_group(scene, group):
    """The door's swing symbol group, or ``None`` when it has none (or is
    lost — the user may have deleted it)."""
    record = registry(scene).get(getattr(group, "uid", "") or "")
    uid = (record or {}).get("symbol")
    if not uid:
        return None
    return next((g for g in scene.groups
                 if getattr(g, "uid", None) == uid), None)


def current_frame(group, fallback: dict) -> dict:
    """Where the door stands now.

    A move or a rotation lands in the parts' ``xform`` — the container's matrix
    is pushed down into them, as with 3D text — so the parts are asked first.
    ``map``/``mapVector`` do the reading, which keeps Qt's row/column order out
    of this file. The stored frame is the fallback for a door with no parts
    left.
    """
    for child in getattr(group, "children", None) or ():
        matrix = getattr(child, "xform", None)
        if matrix is None:
            continue
        origin = matrix.map(QVector3D(0.0, 0.0, 0.0))
        return {
            "origin": opening_mod.as_tuple(origin),
            "x": opening_mod.as_tuple(matrix.mapVector(QVector3D(1, 0, 0))),
            "y": opening_mod.as_tuple(matrix.mapVector(QVector3D(0, 1, 0))),
            "z": opening_mod.as_tuple(matrix.mapVector(QVector3D(0, 0, 1))),
        }
    return dict(fallback or {})


def frame_matrix(frame: dict) -> QMatrix4x4:
    """The local-to-world matrix of a frame, built column by column so that
    Qt's own ordering cannot be got wrong."""
    matrix = QMatrix4x4()
    matrix.setColumn(0, QVector4D(*frame["x"], 0.0))
    matrix.setColumn(1, QVector4D(*frame["y"], 0.0))
    matrix.setColumn(2, QVector4D(*frame["z"], 0.0))
    matrix.setColumn(3, QVector4D(*frame["origin"], 1.0))
    return matrix


# ---- materials --------------------------------------------------------------
def ensure_materials(scene, p: dict) -> None:
    """Make sure the materials the opening paints with exist."""
    from core.materials import Material

    mats = scene.materials
    wanted = {p["frame_mat"]: (120 / 255, 120 / 255, 124 / 255),
              p["leaf_mat"]: (196 / 255, 168 / 255, 120 / 255)}
    if params_mod.glazed(p):
        # Glass reads as glass only if it is not opaque.
        wanted[p["glass_mat"]] = (176 / 255, 196 / 255, 206 / 255)
    for name, colour in wanted.items():
        if name not in mats:
            translucent = params_mod.glazed(p) and name == p["glass_mat"]
            mats[name] = Material(name, color=colour,
                                  opacity=0.35 if translucent else 1.0)


#: Which material each part is painted with. Anything not listed takes the
#: frame's, which is what a threshold and a handle are.
def _paint_for(p: dict, part: str) -> str:
    if part == "Glass":
        return p["glass_mat"]
    if part in ("Leaf", "Sash"):
        return p["leaf_mat"]
    return p["frame_mat"]


#: The tray shows the parts; keep them in an order that reads like a door or a
#: window should be assembled.
PART_ORDER = ("Frame", "Leaf", "Sash", "Glass", "Threshold", "Handle")


def _paint(scene, name: str) -> dict:
    material = scene.materials.get(name)
    if material is None:
        raise opening_mod.OpeningError(
            f'The material "{name}" is not in the document any more. Pick '
            f'another one in the panel.')
    return material.face_attrs()


def ensure_layers(scene, p: dict) -> None:
    """Make sure the door's layer and its symbol's layer exist.

    Two layers, so a view can hide the plan symbol: a plan convention drawn in
    the model has no business in a 3D view or in an elevation.
    """
    from core.layers import Layer

    names = {ly.name for ly in scene.layers}
    for name in (params_mod.layer(p), params_mod.SYMBOL_LAYER):
        if name and name not in names:
            scene.layers.append(Layer(name))
            names.add(name)


# ---- building the geometry --------------------------------------------------
def _mesh_from(faces) -> Mesh:
    """A mesh from the plain faces the geometry module produces."""
    mesh = Mesh()
    for loop, holes in faces:
        face = mesh.add_face([QVector3D(*q) for q in loop],
                             [[QVector3D(*q) for q in h] for h in holes] or None)
        face.attrs = {}
    return mesh


def build_parts(scene, p: dict, wall_depth: float, matrix: QMatrix4x4) -> list:
    """The opening's parts as nested groups, all placed by ``matrix``.

    Whatever :mod:`openings.geometry` produced, in the order a door or a window
    is assembled — so a fixed window simply has fewer of them.
    """
    p = params_mod.normalize(p)
    built = geometry.parts(p, wall_depth)

    parts = []
    for name in PART_ORDER:
        faces = built.get(name)
        if not faces:
            continue
        mesh = _mesh_from(faces)
        attrs = _paint(scene, _paint_for(p, name))
        for face in mesh.faces:
            face.attrs = dict(attrs)
        group = Group(mesh, name=name)
        group.xform = QMatrix4x4(matrix)
        group.component = False
        parts.append(group)
    return parts


def build_symbol(p: dict, wall_depth: float, matrix: QMatrix4x4,
                 layer: str | None) -> Group | None:
    """The swing symbol: the arc, and the opening's outline on the floor.

    Loose **edges**, not faces — a plan symbol is a line convention, and lines
    are what the hidden-line pass draws as lines. In its own top-level group so
    its layer means something.
    """
    p = params_mod.normalize(p)
    segments = geometry.swing_symbol(p, wall_depth)
    outline = geometry.outline_symbol(p, wall_depth)
    if not segments and not outline:
        return None

    mesh = Mesh()
    for a, b in segments:
        if _far_enough(a, b):
            edge = mesh.add_edge(QVector3D(*a), QVector3D(*b))
            edge.layer = layer
    for i in range(len(outline)):
        a, b = outline[i], outline[(i + 1) % len(outline)]
        if _far_enough(a, b):
            edge = mesh.add_edge(QVector3D(*a), QVector3D(*b))
            edge.layer = layer
    if not mesh.edges:
        return None

    group = Group(mesh, name=SYMBOL_NAME)
    group.xform = QMatrix4x4(matrix)
    group.component = False
    group.layer = layer
    return group


def _far_enough(a, b) -> bool:
    return (abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])) > 1e-9


def _next_name(scene, kind: str) -> str:
    """``Door 01``, ``Window 03`` — the first free number of its kind."""
    stem = "Window" if kind == "window" else "Door"
    taken = {g.name for g in scene.groups}
    for i in range(1, 1000):
        name = f"{stem} {i:02d}"
        if name not in taken:
            return name
    return stem


def ifc_class(p: dict) -> str:
    """The IFC class the opening is tagged with — the core's export and the
    BIM panel both read it, and the ifc_editor extension edits the rest."""
    return "IfcWindow" if params_mod.is_window(p) else "IfcDoor"


# ---- create / rebuild / erase ----------------------------------------------
def create(scene, face, click: QVector3D, p: dict, name: str | None = None,
           viewport=None) -> Group:
    """Cut the wall and stand a door in it. Returns the container group.

    The parts are built *before* the wall is touched, so a geometry mistake
    cannot leave a hole with no door in it.
    """
    p = params_mod.normalize(p)
    origin, across, into, up, depth, corners = opening_mod.plan(scene, face,
                                                                click, p)
    ensure_materials(scene, p)
    ensure_layers(scene, p)

    frame = {"origin": opening_mod.as_tuple(origin),
             "x": opening_mod.as_tuple(across),
             "y": opening_mod.as_tuple(into),
             "z": opening_mod.as_tuple(up)}
    matrix = frame_matrix(frame)
    parts = build_parts(scene, p, depth, matrix)      # may raise: nothing cut yet

    record = opening_mod.cut(scene, face, corners, depth)

    name = name or _next_name(scene, p["kind"])
    group = Group(name=name)
    group.adopt(parts)
    group.component = False
    group.layer = params_mod.layer(p)
    group.ifc = {"class": ifc_class(p), "name": name}
    group.ext = {params_mod.KEY: {"params": p, "frame": frame,
                                  "outline": [opening_mod.as_tuple(q)
                                              for q in corners],
                                  "depth": depth,
                                  "opened": False}}
    scene.groups.append(group)

    symbol = build_symbol(p, depth, matrix, params_mod.SYMBOL_LAYER)
    if symbol is not None:
        scene.groups.append(symbol)

    doors = dict(registry(scene))
    doors[group.uid] = {"record": record,
                        "symbol": getattr(symbol, "uid", None)}
    _write_registry(scene, doors)
    if viewport is not None:
        scene.selection = {group}
    return group


def preview(scene, face, click, p: dict):
    """The door as preview faces, in world metres, for a tool to draw while the
    cursor is over a wall — the shape the click would make, before making it.

    ``core.geometry.Face`` is the light polygon the renderer's preview pass
    takes: no mesh, no topology, just what to draw. The parts come from the
    same ``geometry.parts`` the real door is built from, so what is previewed
    and what lands are the same thing by construction.
    """
    from core.geometry import Face as PreviewFace

    p = params_mod.normalize(p)
    try:
        origin, across, into, up, depth, _corners = opening_mod.plan(
            scene, face, click, p)
    except opening_mod.OpeningError:
        return []
    matrix = frame_matrix({"origin": opening_mod.as_tuple(origin),
                           "x": opening_mod.as_tuple(across),
                           "y": opening_mod.as_tuple(into),
                           "z": opening_mod.as_tuple(up)})
    built = geometry.parts(p, depth)
    out = []
    for faces in built.values():
        for loop, holes in faces:
            out.append(PreviewFace(
                vertices=[matrix.map(QVector3D(*q)) for q in loop],
                holes=[[matrix.map(QVector3D(*q)) for q in h] for h in holes],
                attrs={"color": (_PREVIEW[0], _PREVIEW[1], _PREVIEW[2])}))
    return out


#: The warm blue the door is drawn in while it is still only a proposal.
_PREVIEW = (0.63, 0.67, 0.76)


def rebuild(scene, group, p: dict) -> None:
    """New parameters, same place — read from where the door stands now."""
    data = data_of(group)
    if data is None:
        raise opening_mod.OpeningError(
            f'"{getattr(group, "name", "?")}" is not a Door.')
    p = params_mod.normalize(p)
    problems = params_mod.validate(p)
    if problems:
        raise opening_mod.OpeningError(problems[0])

    depth = float(data.get("depth") or 0.2)
    frame = current_frame(group, data.get("frame") or {})
    if not frame.get("origin"):
        raise opening_mod.OpeningError(
            "This door has lost its place in the model — its frame is gone.")

    ensure_materials(scene, p)
    ensure_layers(scene, p)
    matrix = frame_matrix(frame)
    group.children = build_parts(scene, p, depth, matrix)

    stored = dict(data)
    stored["params"] = p
    stored["frame"] = frame
    group.ext = dict(group.ext or {}, **{params_mod.KEY: stored})
    group.ifc = {"class": ifc_class(p), "name": group.name}

    _replace_symbol(scene, group, p, depth, matrix)


def _replace_symbol(scene, group, p: dict, depth: float,
                    matrix: QMatrix4x4) -> None:
    """Put the swing symbol where the door is now, on the right layer."""
    old = symbol_group(scene, group)
    if old is not None:
        if old in scene.groups:
            scene.groups.remove(old)
        scene.selection.discard(old)
    fresh = build_symbol(p, depth, matrix, params_mod.SYMBOL_LAYER)
    if fresh is not None:
        scene.groups.append(fresh)
    doors = dict(registry(scene))
    entry = dict(doors.get(group.uid) or {})
    entry["symbol"] = getattr(fresh, "uid", None)
    doors[group.uid] = entry
    _write_registry(scene, doors)


def erase(scene, group) -> bool:
    """Take the door out and close its opening.

    False when the wall has been edited since — the opening could not be
    closed. The door goes anyway, and the caller says so: leaving a door in
    place because its wall moved would be the worse surprise.
    """
    doors = dict(registry(scene))
    entry = doors.pop(getattr(group, "uid", "") or "", {})
    symbol = symbol_group(scene, group) if entry else None
    for victim in (group, symbol):
        if victim is not None and victim in scene.groups:
            scene.groups.remove(victim)
        if victim is not None:
            scene.selection.discard(victim)
    _write_registry(scene, doors)

    record = entry.get("record")
    if not record:
        return True
    return opening_mod.close(scene, record)


# ---- one undo step ----------------------------------------------------------
class DoorCommand(Command):
    """One user action, one undo step: the loose mesh, the groups (their list,
    their parts, tags, layers and parameters), the plugin data, the materials
    and the layers."""

    def __init__(self, mutate) -> None:
        self.mutate = mutate
        self.before: dict | None = None
        self.after: dict | None = None

    @staticmethod
    def _capture(scene) -> dict:
        return {
            "mesh": scene.mesh.capture_state(),
            "groups": list(scene.groups),
            "state": [(g, list(g.children or ()), g.ifc and dict(g.ifc),
                       copy.deepcopy(getattr(g, "ext", None)),
                       g.xform, getattr(g, "layer", None),
                       getattr(g, "hidden", None))
                      for g in scene.groups],
            "data": copy.deepcopy(scene.plugin_data.get(params_mod.KEY)),
            "mats": dict(scene.materials),
            "layers": list(scene.layers),
        }

    @staticmethod
    def _restore(scene, snap: dict) -> None:
        scene.mesh.restore_state(snap["mesh"])
        scene.groups[:] = snap["groups"]
        for g, kids, ifc, ext, xform, layer, hidden in snap["state"]:
            g.children = list(kids)
            g.ifc = ifc and dict(ifc)
            g.xform = xform
            g.layer = layer
            g.hidden = hidden
            g.ext = copy.deepcopy(ext)
        if snap["data"] is None:
            scene.plugin_data.pop(params_mod.KEY, None)
        else:
            scene.plugin_data[params_mod.KEY] = copy.deepcopy(snap["data"])
        scene.materials.clear()
        scene.materials.update(snap["mats"])
        scene.layers[:] = snap["layers"]
        scene.selection.intersection_update(
            set(scene.mesh.faces) | set(scene.mesh.edges) | set(scene.groups))

    def do(self, scene) -> None:
        if self.after is None:
            self.before = self._capture(scene)
            try:
                self.mutate(scene)
            except BaseException:
                self._restore(scene, self.before)
                raise
            self.after = self._capture(scene)
        else:
            self._restore(scene, self.after)
        scene.version += 1

    def undo(self, scene) -> None:
        if self.before is not None:
            self._restore(scene, self.before)
        scene.version += 1


def run(viewport, mutate, ok_message: str = "") -> bool:
    """Do ``mutate`` as one undo step and refresh; False when it failed, with
    the reason already flashed to the user by the caller."""
    history = viewport.history
    history.execute(DoorCommand(mutate))
    if history.last_error:
        viewport.flash_status(f"Door: {history.last_error}", 6000)
        return False
    notify = getattr(viewport, "notify_scene_changed", None)
    if callable(notify):
        notify()
    viewport.update()
    if ok_message:
        viewport.flash_status(ok_message, 3000)
    return True
