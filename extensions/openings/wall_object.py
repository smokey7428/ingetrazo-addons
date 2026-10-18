# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""The wall as a document object: make one, change it, erase it.

A wall is **one container group**, tagged ``IfcWall``, whose parts are its
skins — ``Buitenblad``, ``Isolatie``, ``Binnenblad`` — each a nested group with
its own material and its own closed volume, so the Parts tray reads like the
build-up does.

Its parameters live in ``group.ext``: the path, the height, the skins. That is
what makes it a wall rather than a mesh — editing it regenerates the geometry,
and later the openings it hosts will regenerate with it.

Everything that changes the document goes through :func:`object.run`, the same
one-undo-step command the openings use.
"""
from __future__ import annotations

from core.group import Group
from core.mesh import Mesh
from PySide6.QtGui import QVector3D

from . import object as object_mod
from . import opening as opening_mod
from . import wall_geometry
from . import walls

#: What a wall's own group is called in the document.
NAME = "Wall"


# ---- reading a wall ---------------------------------------------------------
def data_of(group) -> dict | None:
    """The wall's own record on ``group``, or ``None`` if it is not a wall."""
    ext = getattr(group, "ext", None) or {}
    found = ext.get(walls.KEY) if isinstance(ext, dict) else None
    if isinstance(found, dict) and found.get("kind") == walls.KIND:
        return found
    return None


def is_wall(group) -> bool:
    return data_of(group) is not None


def wall_params(group) -> dict:
    """The wall's parameters, normalised — never the raw stored dict."""
    return walls.normalize((data_of(group) or {}))


def _next_name(scene) -> str:
    taken = {g.name for g in scene.groups}
    for i in range(1, 1000):
        name = f"Wall {i:02d}"
        if name not in taken:
            return name
    return NAME


# ---- building it ------------------------------------------------------------
def ensure_materials(scene, w: dict) -> None:
    """Make sure a material exists for every skin."""
    from core.materials import Material

    palette = {"Brick": (0.62, 0.35, 0.29),
               "Insulation": (0.90, 0.82, 0.52),
               "Block": (0.78, 0.76, 0.72)}
    for skin in w["skins"]:
        name = skin["material"]
        if name and name not in scene.materials:
            scene.materials[name] = Material(
                name, color=palette.get(name, (0.75, 0.74, 0.72)))


def _mesh_from(faces, attrs: dict) -> Mesh:
    mesh = Mesh()
    for loop, holes in faces:
        face = mesh.add_face([QVector3D(*q) for q in loop],
                             [[QVector3D(*q) for q in h] for h in holes] or None)
        face.attrs = dict(attrs)
    return mesh


def build_skins(scene, w: dict) -> list:
    """One nested group per skin, named and painted as the build-up says."""
    w = walls.normalize(w)
    ensure_materials(scene, w)
    built = wall_geometry.skin_faces(w)

    parts = []
    for skin in w["skins"]:
        faces = built.get(skin["name"])
        if not faces:
            continue
        material = scene.materials.get(skin["material"])
        attrs = material.face_attrs() if material is not None else {}
        group = Group(_mesh_from(faces, attrs), name=skin["name"])
        group.component = False
        parts.append(group)
    return parts


# ---- create / regenerate / erase -------------------------------------------
def create(scene, w: dict, name: str | None = None, viewport=None) -> Group:
    """Make the wall. Returns its container group."""
    w = walls.normalize(w)
    problems = walls.validate(w)
    if problems:
        raise opening_mod.OpeningError(problems[0])

    name = name or _next_name(scene)
    group = Group(name=name)
    group.adopt(build_skins(scene, w))
    group.component = False
    group.ifc = {"class": "IfcWall", "name": name}
    group.ext = {walls.KEY: dict(w, kind=walls.KIND)}
    scene.groups.append(group)
    if viewport is not None:
        scene.selection = {group}
    return group


def regenerate(scene, group, w: dict) -> None:
    """Same wall, new numbers: the skins are rebuilt from the parameters."""
    if data_of(group) is None:
        raise opening_mod.OpeningError(
            f'"{getattr(group, "name", "?")}" is not a wall of ours.')
    w = walls.normalize(w)
    problems = walls.validate(w)
    if problems:
        raise opening_mod.OpeningError(problems[0])

    group.children = build_skins(scene, w)
    group.ext = dict(group.ext or {}, **{walls.KEY: dict(w, kind=walls.KIND)})
    group.ifc = {"class": "IfcWall", "name": group.name}


def quantities(w: dict) -> list:
    """``[{name, material, area, volume, mass}, …]`` — one row per skin.

    The area is the **wall face** a builder prices (volume ÷ thickness, so a
    mitred skin is measured by what it is made of, not by a bounding box), and
    the mass is the volume times the material's density where we know it.

    A composite wall is a stack of solids, so this — not one number for "the
    wall" — is what a take-off wants: m² of brick, m² of insulation, m³ of
    block.
    """
    from . import profiles

    w = walls.normalize(w)
    built = wall_geometry.skin_faces(w)
    out = []
    for skin, _from, _to in walls.offsets(w):
        faces = built.get(skin["name"]) or []
        volume = wall_geometry.volume({skin['name']: faces}) if faces else 0.0
        thickness = float(skin["thickness"]) or 1.0
        density = profiles.DENSITY.get(skin["material"])
        out.append({
            "name": skin["name"],
            "material": skin["material"],
            "volume": volume,
            "area": volume / thickness,
            "mass": volume * density if density else None,
        })
    return out


def erase(scene, group) -> bool:
    """Take the wall out. True — there is nothing to close up behind it."""
    if group in scene.groups:
        scene.groups.remove(group)
    scene.selection.discard(group)
    return True


# ---- the preview ------------------------------------------------------------
def preview(scene, w: dict) -> list:
    """The wall as preview faces, for a tool to draw while it is being placed."""
    from core.geometry import Face as PreviewFace

    w = walls.normalize(w)
    if len(w["path"]) < 2:
        return []
    palette = {"Brick": (0.62, 0.35, 0.29), "Insulation": (0.90, 0.82, 0.52),
               "Block": (0.78, 0.76, 0.72)}
    out = []
    built = wall_geometry.skin_faces(w)
    for skin in w["skins"]:
        colour = palette.get(skin["material"], (0.75, 0.74, 0.72))
        for loop, holes in built.get(skin["name"], ()):
            out.append(PreviewFace(
                vertices=[QVector3D(*q) for q in loop],
                holes=[[QVector3D(*q) for q in h] for h in holes],
                attrs={"color": colour}))
    return out
