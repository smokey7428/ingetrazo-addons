# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""The wall tool: draw a wall like a polyline.

Click the points a wall runs through — it is drawn along its **centre line**,
the way a wall is drawn in a plan — and finish with Enter or a double-click.
Every click shows the real wall, skins and all, as a preview: the same geometry
the commit will make, because it comes from the same generator.

It stays active after a wall is finished, so a plan is one continuous flow;
Esc leaves.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from tools.base import Tool

from . import object as object_mod
from . import wall_object as wall_obj

log = logging.getLogger("ingetrazo.plugins")

#: The key the tool is registered under in the host's tool table.
TOOL_KEY = "openings_wall"


class WallTool(Tool):
    """Click points to draw a wall; Enter or double-click finishes it."""

    uses_snap = True               # a wall runs through points you can snap to
    box_select = False
    wireframe_color = (0.35, 0.55, 0.30, 1.0)

    def __init__(self, app, panel, text) -> None:
        self.app = app
        self.panel = panel
        self._t = text
        self.name = text("Wall")
        self.description = text(
            "Draw a wall along a polyline, built up from the panel's skins.")
        self._points: list = []
        self._hover = None
        self._preview: list = []

    # ---- lifecycle ----
    def on_activate(self, viewport) -> None:
        self._reset()
        viewport.flash_status(self._t(
            "Click the points the wall runs through. Enter or a double-click "
            "finishes it; Esc cancels."), 6000)

    def on_deactivate(self, viewport) -> None:
        self._reset()

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self._points = []
        self._hover = None
        self._preview = []

    # ---- drawing ----
    def on_click(self, ctx) -> None:
        point = QVector3D(ctx.world)
        if self._points and _same(point, self._points[-1]):
            return                              # a click on the last point: ignore
        self._points.append(point)
        self._rebuild()
        ctx.viewport.update()

    def on_hover(self, ctx) -> None:
        point = QVector3D(ctx.world)
        if self._points and _same(point, self._hover):
            return
        self._hover = point
        self._rebuild()
        ctx.viewport.update()

    def on_double_click(self, ctx) -> None:
        """A double-click finishes: the point it lands on is the last one."""
        if self._points:
            self.finish(ctx.viewport)

    def on_key(self, viewport, key: int, modifiers) -> bool:
        if key in (int(Qt.Key_Return), int(Qt.Key_Enter)):
            self.finish(viewport)
            return True
        if key == int(Qt.Key_Escape):
            self.on_cancel(viewport)
            return True
        if key == int(Qt.Key_Backspace) and self._points:
            # Step back one point, rather than starting the run again.
            self._points.pop()
            self._rebuild()
            viewport.update()
            return True
        return False

    # ---- finishing ----
    def finish(self, viewport) -> None:
        if len(self._points) < 2:
            self._reset()
            viewport.flash_status(self._t(
                "A wall needs at least two points."), 4000)
            viewport.update()
            return
        points = list(self._points)
        self._reset()
        viewport.update()

        parameters = self.panel.draft()
        parameters["path"] = [[p.x(), p.y()] for p in points]
        parameters["base"] = min(p.z() for p in points)
        problems = wall_obj.walls.validate(
            wall_obj.walls.normalize(parameters))
        if problems:
            viewport.flash_status(problems[0], 5000)
            return

        made: dict = {}

        def make(scene):
            made["wall"] = wall_obj.create(scene, parameters, viewport=viewport)

        if object_mod.run(viewport, make, self._t("Wall drawn"), label="Wall"):
            wall = made.get("wall")
            if wall is not None:
                self.panel.show_wall(wall)

    # ---- what the clicks would make ----
    def _rebuild(self) -> None:
        points = list(self._points)
        if self._hover is not None:
            points.append(self._hover)
        if len(points) < 2:
            self._preview = []
            return
        parameters = self.panel.draft()
        parameters["path"] = [[p.x(), p.y()] for p in points]
        parameters["base"] = min(p.z() for p in points)
        try:
            self._preview = wall_obj.preview(self.app.scene, parameters)
        except Exception:                       # noqa: BLE001 — never break paint
            log.exception("openings: could not preview the wall")
            self._preview = []

    def preview_faces(self):
        """The renderer asks for this every frame."""
        return list(self._preview)


def _same(a, b, tol: float = 1e-4) -> bool:
    return (b is not None and abs(a.x() - b.x()) < tol
            and abs(a.y() - b.y()) < tol and abs(a.z() - b.z()) < tol)
