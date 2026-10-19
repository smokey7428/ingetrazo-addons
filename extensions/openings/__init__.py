# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Doors & windows — parametric doors cut into walls, the Revit way.

Tested with IngeTrazo 0.5.8 (extension API 2).

* **Click a wall, get a door.** The tool picks the wall face under the cursor,
  draws what the click would make, and cuts a real opening: the wall keeps its
  material, its layer and its BIM tag through the reveal, and stays a closed
  solid so its volume is still reported honestly.
* **Parametric.** The parameters live on the container group (``group.ext``),
  so they travel with a copy, survive save and open, and editing rebuilds the
  door *where it stands*.
* **Its parts are objects**, not one lump: lining, leaf, threshold and handle
  are separate groups, in the Parts tray, each with its own material.
* **A plan symbol** — the swing arc — on a layer of its own, with Plan /
  Elevation / 3D scenes that show it in the one view where it belongs.
* **IFC**: the door is tagged ``IfcDoor``, so the core's export already writes
  the class, the name, the geometry and OverallHeight/OverallWidth. Its full
  attribute set and property sets are the ``ifc_editor`` extension's job —
  the two are meant to be used together.

The interactive tool is registered through :mod:`openings.host`, the one place
in this extension that touches IngeTrazo's private API, because 0.5.8 has no
public way to register a tool. That module says why, and refuses gracefully.

Install: ``./dev/install.sh``, then restart IngeTrazo.
"""
from __future__ import annotations

import logging

from core.i18n import current_language

log = logging.getLogger("ingetrazo.plugins")

_TEXTS = {
    "es": {
        "Openings": "Huecos",
        "Doors & windows": "Puertas y ventanas",
        "Place…": "Colocar…",
        "Edit…": "Editar…",
        "Erase": "Eliminar",
        "Door": "Puerta",
        "Place a door": "Colocar una puerta",
        "Cut an opening in a wall and stand a parametric door in it.":
            "Abre un hueco en un muro y coloca en él una puerta paramétrica.",
        "Edit door": "Editar la puerta",
        "Erase door": "Eliminar la puerta",
        "Make plan / elevation / 3D": "Crear planta / alzado / 3D",
        "Redraw the swing symbols": "Redibujar los símbolos de barrido",
        "Plan, elevation and 3D scenes, showing the door symbols where they "
        "belong.":
            "Escenas de planta, alzado y 3D, con los símbolos de las puertas "
            "donde corresponde.",
        "Puts each door's swing symbol back where the door is now.":
            "Devuelve el símbolo de barrido de cada puerta a donde está ahora "
            "la puerta.",
        "Doors — plan": "Puertas — planta",
        "Walls": "Muros",
        "Wall": "Muro",
        "Draw a wall…": "Dibujar un muro…",
        "Walls panel…": "Panel de muros…",
        "Take-off": "Metrado",
        "Take-off…": "Metrado…",
        "Place a door or window…": "Colocar una puerta o ventana…",
        "Draw a wall along a polyline, built from the panel's skins.":
            "Dibuja un muro por una polilínea, construido con las capas del "
            "panel.",
        "Draw a wall along a polyline, built up from the panel's skins.":
            "Dibuja un muro por una polilínea, construido con las capas del "
            "panel.",
        "Point at a face of a wall and click to place the opening. The wall "
        "must not be inside a group. Esc when you are done.":
            "Apunta a una cara de un muro y haz clic para colocar el hueco. El "
            "muro no puede estar dentro de un grupo. Esc para terminar.",
        "That face is inside a group, and a group's geometry cannot be cut "
        "until it is open. Double-click into the group and place the door "
        "inside it, or explode the group first.":
            "Esa cara está dentro de un grupo, y la geometría de un grupo no "
            "se puede cortar hasta abrirlo. Haz doble clic para entrar en el "
            "grupo y coloca la puerta dentro, o desagrupa primero.",
        "Point at a face of the wall you want the door or window in.":
            "Apunta a una cara del muro donde quieras la puerta o ventana.",
        "Placed": "Colocado",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


def setup(app) -> None:
    """Called once, when the main window is built."""
    from . import host, params as params_mod, scenes
    from .object import is_opening
    from .panel import OpeningsPanel
    from .tool import TOOL_KEY, DoorTool
    from .takeoff_panel import TakeoffPanel
    from .wall_object import is_wall
    from .wall_panel import WallsPanel
    from .wall_tool import TOOL_KEY as WALL_TOOL_KEY
    from .wall_tool import WallTool

    panel = OpeningsPanel(app)
    dock = app.add_panel(_t("Openings"), panel)
    panel.attach_dock(dock)
    _remember(panel)

    # Walls are a panel of their own, beside the openings': one is what you
    # draw, the other is what you put in it.
    walls_panel = WallsPanel(app)
    walls_dock = app.add_panel(_t("Walls"), walls_panel, name="walls")
    walls_panel.attach_dock(walls_dock)
    _remember(walls_panel)

    # The take-off, which the core's BIM panel cannot do for a composite wall.
    takeoff_panel = TakeoffPanel(app)
    takeoff_dock = app.add_panel(_t("Take-off"), takeoff_panel,
                                 name="takeoff")
    takeoff_panel.attach_dock(takeoff_dock)
    _remember(takeoff_panel)

    wall_tool = WallTool(app, walls_panel, _t)
    if host.register(app, WALL_TOOL_KEY, wall_tool, _t("Wall"),
                     _t("Draw a wall along a polyline, built from the panel's "
                        "skins.")):
        walls_panel.attach_tool(wall_tool)

    tool = DoorTool(app, panel, _t)
    if host.register(app, TOOL_KEY, tool, _t("Door"),
                     _t("Cut an opening in a wall and stand a parametric door "
                        "in it.")):
        panel.attach_tool(tool)
    else:
        log.warning("openings: the door tool is unavailable in this build; "
                    "the panel still works")

    # Our own submenu: several commands, and the panel's buttons are repeats
    # of the two that matter most.
    sub = app.add_menu(_t("Doors & windows"))
    if sub is not None:
        sub.addAction(_t("Place a door or window…"),
                      lambda: host.activate(app, TOOL_KEY))
        sub.addAction(_t("Draw a wall…"),
                      lambda: host.activate(app, WALL_TOOL_KEY))
        sub.addAction(_t("Walls panel…"),
                      lambda: app.show_panel(walls_dock))
        sub.addAction(_t("Take-off…"),
                      lambda: app.show_panel(takeoff_dock))
        sub.addAction(_t("Edit…"), lambda: app.show_panel(dock))
        sub.addAction(_t("Erase"), panel._on_erase)
        sub.addSeparator()
        sub.addAction(_t("Make plan / elevation / 3D"),
                      lambda: scenes.make(app.viewport,
                                          params_mod.SYMBOL_LAYER))
        sub.addAction(_t("Redraw the swing symbols"),
                      lambda: _scenes_refresh(app))

    app.add_context_menu(_context_menu)
    app.add_outliner_kind(_outliner_kind)


def _scenes_refresh(app) -> None:
    from . import scenes

    count = scenes.refresh(app.viewport)
    if count:
        app.viewport.flash_status(
            _t("Swing symbols redrawn for {n} door(s).", n=count), 4000)


def _context_menu(menu, selection) -> None:
    """Right-click entries, after the selection's own."""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction

    from .object import is_opening

    items = [item for item in selection if is_opening(item)]
    if not items:
        return
    menu.addSeparator()
    action = QAction(_t("Edit"), menu)
    # Through a single shot, so the dialog-free panel is raised after the menu
    # has closed rather than under it.
    action.triggered.connect(lambda _c=False: QTimer.singleShot(
        0, lambda: _raise_panel()))
    menu.addAction(action)
    erase = QAction(_t("Erase"), menu)
    erase.triggered.connect(lambda _c=False: QTimer.singleShot(
        0, lambda: _erase_selection()))
    menu.addAction(erase)


def _panel():
    """The doors panel this extension added at setup."""
    from .panel import OpeningsPanel

    for widget in _PANELS:
        if isinstance(widget, OpeningsPanel):
            return widget
    return None


def _raise_panel() -> None:
    panel = _panel()
    if panel is not None and panel._dock is not None:
        panel._app.show_panel(panel._dock)


def _erase_selection() -> None:
    panel = _panel()
    if panel is not None:
        panel._on_erase()


def _outliner_kind(group) -> dict | None:
    """What our groups are, in the Browser: the opening, its symbol and its
    parts — the Type column the filter finds, and the tooltip that reads out
    what the thing actually is."""
    from . import object as object_mod
    from . import params as params_mod
    from . import profiles

    from . import wall_object as wall_mod

    wall_data = wall_mod.data_of(group)
    if wall_data is not None:
        w = wall_mod.walls.normalize(wall_data)
        return {"type": "Wall", "props": [
            ("Build-up", f"{len(w['skins'])} skins, "
                         f"{wall_mod.walls.total_thickness(w) * 1000:.0f} mm"),
            ("Length", f"{wall_mod.walls.length(w):.2f} m"),
            ("Height", f"{w['height']:.2f} m"),
        ]}

    data = object_mod.data_of(group)
    if data is not None:
        values = params_mod.normalize(data.get("params"))
        props = [
            ("Size", f"{values['width'] * 1000:.0f} × "
                     f"{values['height'] * 1000:.0f} mm"),
            ("Type", profiles.label(values["kind"], values["type"])),
        ]
        if params_mod.moves(values):
            props.append(("Handing",
                          f"{values['handing']}, opens {values['swing']}"))
            props.append(("Open angle", f"{values['open_angle']:.0f}°"))
        else:
            props.append(("Fixed", "nothing opens"))
        return {"type": "Window" if params_mod.is_window(values) else "Door",
                "props": props}
    if getattr(group, "name", "") == object_mod.SYMBOL_NAME:
        return {"type": "Swing symbol",
                "props": [("Layer", getattr(group, "layer", "") or "")]}
    return None


#: Set at setup, so the context-menu entries can find the panel without
#: reaching through the window's internals.
_PANELS: list = []


def _remember(panel) -> None:
    _PANELS.append(panel)
