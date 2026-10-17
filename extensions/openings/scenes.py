# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The views a door needs, and the one layer trick that makes them work.

A door needs two things the platform does not give per object: a **plan
symbol** (the swing arc) and a way to keep it out of the views where it is
wrong. IngeTrazo has no per-object 2D representation — plan and elevation come
from the hidden-line pass over the 3D model — so the arc is real geometry on a
layer of its own, and *which layers a view shows* is the only switch there is.

A layer is one global flag, and a **scene** is a snapshot of those flags, so a
scene per kind of view is how this is meant to be done here:

=============  ==========================================  ===============
Scene          Camera                                       Doors — plan
=============  ==========================================  ===============
Plan           top, parallel                                shown
Elevation      front, parallel                              hidden
3D             isometric, perspective                       hidden
=============  ==========================================  ===============

Created through ``SnapshotImport``, which is the command that tracks views the
way it tracks groups and layers — so making the three scenes is **one undo
step**, and undo takes them away again.

The honest wart: a door that is *moved* after its symbol was drawn leaves the
symbol behind, because nothing here is associative. ``refresh`` redraws every
door's symbol from where the door stands now, which is the repair.
"""
from __future__ import annotations

import logging

log = logging.getLogger("ingetrazo.plugins.openings")

#: ``(name, camera view, perspective, show the swing symbol)``
SCENES = (
    ("Plan", "top", False, True),
    ("Elevation", "front", False, False),
    ("3D", "iso", True, False),
)


def _scene_state(scene, camera) -> dict:
    return {
        "layers": [(ly, ly.visible) for ly in scene.layers],
        "camera": (camera.target, camera.distance, camera.yaw, camera.pitch,
                   getattr(camera, "perspective", True)),
    }


def _restore(scene, camera, kept: dict) -> None:
    for layer, visible in kept["layers"]:
        layer.visible = visible
    target, distance, yaw, pitch, perspective = kept["camera"]
    camera.target = target
    camera.distance = distance
    camera.yaw = yaw
    camera.pitch = pitch
    if hasattr(camera, "perspective"):
        camera.perspective = perspective


def make(viewport, symbol_layer: str) -> list:
    """Make (or remake) the Plan, Elevation and 3D scenes. No-op in an empty
    document, and one undo step.

    Remaking replaces a scene of the same name rather than piling a second one
    up, so the menu entry is safe to press twice.
    """
    from core.history import SnapshotImport
    from core.saved_views import SavedView

    scene = viewport.scene
    camera = getattr(viewport, "camera", None)
    if camera is None or not scene.layers:
        return []

    made: list = []

    def mutate(target_scene):
        kept = _scene_state(target_scene, camera)
        try:
            by_name = {ly.name: ly for ly in target_scene.layers}
            for name, view, perspective, show_symbol in SCENES:
                camera.set_view(view)
                if hasattr(camera, "perspective"):
                    camera.perspective = perspective
                layer = by_name.get(symbol_layer)
                if layer is not None:
                    layer.visible = show_symbol
                fresh = SavedView.capture(name, target_scene, camera)
                old = next((v for v in target_scene.saved_views
                            if getattr(v, "name", None) == name), None)
                if old is not None:
                    target_scene.saved_views.remove(old)
                target_scene.saved_views.append(fresh)
                made.append(name)
        finally:
            _restore(target_scene, camera, kept)

    viewport.history.execute(SnapshotImport(mutate))
    if viewport.history.last_error:
        log.warning("openings: could not make the scenes (%s)",
                    viewport.history.last_error)
        return []
    notify = getattr(viewport, "notify_scene_changed", None)
    if callable(notify):
        notify()
    viewport.update()
    return made


def refresh(viewport) -> int:
    """Redraw every opening's swing symbol where the door stands now.

    The repair for the wart above: nothing associates the symbol with its door
    but our own bookkeeping, so a door that was moved by hand has left its
    symbol where it used to be, and this puts it back. Returns how many doors
    were put right.
    """
    from . import object as object_mod

    scene = viewport.scene
    doors = [g for g in scene.groups if object_mod.is_opening(g)]
    if not doors:
        return 0

    def mutate(target):
        for door in doors:
            if door not in target.groups:
                continue
            values = object_mod.opening_params(door)
            data = object_mod.data_of(door) or {}
            depth = float(data.get("depth") or 0.2)
            frame = object_mod.current_frame(door, data.get("frame") or {})
            if not frame.get("origin"):
                continue
            object_mod._replace_symbol(target, door, values, depth,
                                       object_mod.frame_matrix(frame))

    object_mod.run(viewport, mutate, "")
    return len(doors)
