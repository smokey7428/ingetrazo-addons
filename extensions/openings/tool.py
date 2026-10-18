# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
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

import logging

from PySide6.QtGui import QVector3D

from tools.base import Tool

from . import hosting
from . import opening as opening_mod
from . import object as object_mod
from . import params as params_mod

log = logging.getLogger("ingetrazo.plugins")

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
        self._reason = ""
        self._hosted = None
        self._preview: list = []

    # ---- lifecycle ----
    def on_activate(self, viewport) -> None:
        self._reset()
        viewport.flash_status(self._t(
            "Point at a face of a wall and click to place the opening. The "
            "wall must not be inside a group. Esc when you are done."), 6000)

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self._face = None
        self._point = None
        self._reason = ""
        self._hosted = None
        self._preview = []

    # ---- the cursor ----
    def _rescan(self, ctx) -> bool:
        """Pick the face under the cursor and remember where on it we are.

        Returns whether anything changed, so the preview and the explanation are
        drawn once per new position rather than per frame.

        When nothing is picked, :meth:`_why_not` finds out *why* — and the
        answer is reported, because a cursor that does nothing and says nothing
        is the worst possible feedback.
        """
        from . import host

        viewport = ctx.viewport
        x, y = ctx.screen.x(), ctx.screen.y()
        face = viewport.pick_face(x, y)

        # A wall of ours is a group, so it is not in the loose mesh at all:
        # ask the wider picker whether what is under the cursor belongs to one.
        owner = self._host_owner(viewport, x, y)
        hosted = None
        if owner is not None:
            any_pick = getattr(viewport, "pick_face_any", None)
            picked, _group = any_pick(x, y)
            if picked is not None:
                hosted = (picked, owner)

        point = host.world_under_cursor(self.app, x, y) \
            if (face is not None or hosted is not None) else None
        if hosted is not None:
            reason = ""
        elif face is not None:
            reason = ""
        else:
            reason = self._why_not(viewport, x, y)

        changed = (face is not self._face or _key(point) != _key(self._point)
                   or reason != self._reason
                   or (hosted or (None, None))[1] is not
                   (self._hosted or (None, None))[1])
        self._face, self._point, self._reason = face, point, reason
        self._hosted = hosted
        return changed

    def _host_owner(self, viewport, x: float, y: float):
        """The wall of ours under the cursor, when what is there belongs to one."""
        from . import wall_object as wall_mod

        any_pick = getattr(viewport, "pick_face_any", None)
        if not callable(any_pick):
            return None
        try:
            _face, owner = any_pick(x, y)
        except Exception:                              # noqa: BLE001
            return None
        return owner if owner is not None and wall_mod.is_wall(owner) else None

    def _why_not(self, viewport, x: float, y: float) -> str:
        """Why no face was picked, in words the user can act on.

        There are exactly two answers, and they need telling apart: nothing
        under the cursor at all, or a face that belongs to a **group** —
        ``pick_face`` only ever answers with loose geometry, and that is the
        platform's rule, not ours: Push/Pull likewise refuses a face inside a
        container until the group is opened. So the message says what to do
        rather than leaving the user clicking at nothing.
        """
        any_pick = getattr(viewport, "pick_face_any", None)
        if not callable(any_pick):
            return ""
        try:
            other, owner = any_pick(x, y)
        except Exception:                              # noqa: BLE001
            return ""
        if other is None:
            return ""
        del owner                       # any face behind a group face is the case
        return self._t(
            "That face is inside a group, and a group's geometry cannot be cut "
            "until it is open. Double-click into the group and place the door "
            "inside it, or explode the group first.")

    def on_hover(self, ctx) -> None:
        if self._rescan(ctx):
            self._rebuild(ctx.viewport)
            ctx.viewport.update()

    def on_click(self, ctx) -> None:
        viewport = ctx.viewport
        self._rescan(ctx)
        if (self._face is None or self._point is None) \
                and self._hosted is None:
            viewport.flash_status(
                self._reason or self._t("Point at a face of the wall you want "
                                        "the door or window in."), 5000)
            return
        parameters = self.panel.draft()
        problems = params_mod.validate(parameters)
        if problems:
            viewport.flash_status(problems[0], 5000)
            return

        placed: dict = {}

        if self._hosted is not None:
            # A wall of ours: the opening becomes data on it, and the wall
            # regenerates around the hole. Nothing is cut.
            picked, wall = self._hosted
            normal = picked.normal()

            def make_hosted(scene):
                placed["item"] = hosting.add(scene, wall, self._point, normal,
                                             parameters, viewport=viewport)

            if object_mod.run(viewport, make_hosted, self._t("Placed")):
                item = placed.get("item")
                if item is not None:
                    self.panel.show_opening(item)
                self._rebuild(viewport)
            return

        def make(scene):
            placed["item"] = object_mod.create(
                scene, self._face, self._point, parameters, viewport=viewport)

        if object_mod.run(viewport, make, self._t("Placed")):
            item = placed.get("item")
            if item is not None:
                self.panel.show_opening(item)
            # Stay active: a plan is several openings, and the tool is re-entered
            # deliberately with the same click that leaves it.
            self._rebuild(viewport)

    # ---- what the click would make ----
    def _rebuild(self, viewport) -> None:
        """Build the preview once per (face, point) rather than per paint: the
        plan reads the wall's far side, which is a scan of the mesh."""
        self._preview = []
        if self._hosted is not None and self._point is not None:
            picked, wall = self._hosted
            parameters = self.panel.draft()
            try:
                frame, _opening, depth = hosting.placement(
                    wall, self._point, picked.normal(), parameters)
                self._preview = object_mod.preview_placement(
                    viewport.scene, parameters, frame, depth)
            except opening_mod.OpeningError as exc:
                viewport.flash_status(str(exc), 5000)
            except Exception:                          # noqa: BLE001
                log.exception("openings: could not preview the opening")
            return
        if self._face is None or self._point is None:
            if self._reason:
                viewport.flash_status(self._reason, 6000)
            return
        try:
            self._preview = object_mod.preview(
                viewport.scene, self._face, self._point, self.panel.draft())
        except opening_mod.OpeningError as exc:
            # The wall cannot take this opening — say so now, not on the click.
            viewport.flash_status(str(exc), 5000)
        except Exception:                              # noqa: BLE001
            log.exception("openings: could not preview the opening")

    def preview_faces(self):
        """The renderer asks for this every frame."""
        return list(self._preview)


def _key(point) -> tuple | None:
    if point is None:
        return None
    return (round(point.x(), 3), round(point.y(), 3), round(point.z(), 3))
