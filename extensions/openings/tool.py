# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The door tool: click a wall, get a door.

Deliberately like every other IngeTrazo tool — activate it, the cursor picks
geometry, what you would get is drawn before you commit, Esc leaves. The
differences are only the ones a hosted object needs:

* it picks **a face**, not a point, because a door is cut into a wall;
* it shows the wall's refusal *as a message*, not as silence: a face with no
  wall behind it, or one too small for the door, says so while the cursor is
  still moving;
* it stays active after placing, so a floor plan can be worked through without
  reaching for the toolbar between doors.

The tool is registered through :mod:`openings.host`, which is where the one
piece of private API lives.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from tools.base import Tool

from . import opening as opening_mod
from . import object as object_mod
from . import params as params_mod

#: The key the tool is registered under in the host's tool table.
TOOL_KEY = "openings_door"


class DoorTool(Tool):
    """Click a wall face to cut an opening and stand a door in it."""

    uses_snap = False          # it picks a face, not a point on one
    box_select = False
    wireframe_color = (0.30, 0.55, 0.85, 1.0)

    def __init__(self, app, panel, text) -> None:
        self.app = app
        self.panel = panel
        self._t = text
        self.name = text("Door")
        self.description = text(
            "Cut an opening in a wall and stand a parametric door in it.")
        self._face = None
        self._point = None
        self._preview: list = []
        self._preview_key = None

    # ---- lifecycle ----
    def on_activate(self, viewport) -> None:
        self._reset()
        viewport.flash_status(self._t(
            "Click a wall face to place a door. Esc when you are done."), 5000)

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self._face = None
        self._point = None
        self._preview = []
        self._preview_key = None

    # ---- the cursor ----
    def _under_cursor(self, ctx) -> bool:
        """Pick the face under the cursor and remember where on it we are.

        The hit point comes from the viewport's own reading of the cursor
        (nearest geometry, else the ground), reached through
        :mod:`openings.host` — it is the same number the snap engine works
        from, and recomputing it here would be a second, worse opinion.
        """
        from . import host

        viewport = ctx.viewport
        face = viewport.pick_face(ctx.screen.x(), ctx.screen.y())
        point = host.world_under_cursor(self.app, ctx.screen.x(),
                                        ctx.screen.y())
        changed = face is not self._face or _key(point) != _key(self._point)
        self._face, self._point = face, point
        return changed

    def on_hover(self, ctx) -> None:
        if self._under_cursor(ctx):
            self._rebuild_preview(ctx.viewport)
            ctx.viewport.update()

    def on_click(self, ctx) -> None:
        viewport = ctx.viewport
        self._under_cursor(ctx)
        face = self._face
        if face is None or self._point is None:
            viewport.flash_status(self._t(
                "Click on a face of the wall you want the door in."), 3500)
            return
        parameters = self.panel.draft()
        problems = params_mod.validate(parameters)
        if problems:
            viewport.flash_status(problems[0], 5000)
            return

        placed: dict = {}

        def make(scene):
            placed["door"] = object_mod.create(
                scene, face, self._point, parameters, viewport=viewport)

        if object_mod.run(viewport, make, self._t("Door placed")):
            door = placed.get("door")
            if door is not None:
                self.panel.show_door(door)
            # Stay active: a plan is several doors, and the tool is re-entered
            # deliberately with the same click that leaves it.
            self._rebuild_preview(viewport)

    # ---- what the click would make ----
    def _rebuild_preview(self, viewport) -> None:
        """Build the preview once per (face, point) rather than per paint: the
        plan reads the wall's far side, which is a scan of the mesh."""
        key = (id(self._face), _key(self._point))
        if key == self._preview_key:
            return
        self._preview_key = key
        self._preview = []
        self.reason = ""
        if self._face is None or self._point is None:
            return
        try:
            self._preview = object_mod.preview(
                viewport.scene, self._face, self._point, self.panel.draft())
        except opening_mod.OpeningError as exc:
            self.reason = str(exc)
            viewport.flash_status(str(exc), 4000)
        except Exception as exc:                       # noqa: BLE001
            self.reason = str(exc)

    def preview_faces(self):
        """The renderer asks for this every frame."""
        return list(self._preview)


def _key(point) -> tuple | None:
    if point is None:
        return None
    return (round(point.x(), 3), round(point.y(), 3), round(point.z(), 3))
