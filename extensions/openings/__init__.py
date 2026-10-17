# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
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
        "Doors": "Puertas",
        "Doors & windows": "Puertas y ventanas",
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
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


def setup(app) -> None:
    """Called once, when the main window is built."""
    from . import host, scenes
    from .object import is_door
    from .panel import DoorsPanel
    from .tool import TOOL_KEY, DoorTool

    panel = DoorsPanel(app)
    dock = app.add_panel(_t("Doors"), panel)
    panel.attach_dock(dock)
    _remember(panel)

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
        sub.addAction(_t("Place a door"),
                      lambda: host.activate(app, TOOL_KEY))
        sub.addAction(_t("Edit door"), lambda: app.show_panel(dock))
        sub.addAction(_t("Erase door"), panel._on_erase)
        sub.addSeparator()
        sub.addAction(_t("Make plan / elevation / 3D"),
                      lambda: scenes.make(app.viewport,
                                          panel.draft()["symbol_layer"]))
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

    from .object import is_door

    doors = [item for item in selection if is_door(item)]
    if not doors:
        return
    menu.addSeparator()
    action = QAction(_t("Edit door"), menu)
    # Through a single shot, so the dialog-free panel is raised after the menu
    # has closed rather than under it.
    action.triggered.connect(lambda _c=False: QTimer.singleShot(
        0, lambda: _raise_panel()))
    menu.addAction(action)
    erase = QAction(_t("Erase door"), menu)
    erase.triggered.connect(lambda _c=False: QTimer.singleShot(
        0, lambda: _erase_selection()))
    menu.addAction(erase)


def _panel():
    """The doors panel this extension added at setup."""
    from .panel import DoorsPanel

    for widget in _PANELS:
        if isinstance(widget, DoorsPanel):
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
    """What our groups are, in the Browser: the door, its symbol, its parts."""
    from . import object as object_mod
    from . import params as params_mod

    data = object_mod.data_of(group)
    if data is not None:
        values = params_mod.normalize(data.get("params"))
        return {"type": "Door", "props": [
            ("Size", f"{values['width'] * 1000:.0f} × "
                     f"{values['height'] * 1000:.0f} mm"),
            ("Handing", values["handing"]),
            ("Swing", f"{values['swing']}, {values['open_angle']:.0f}°"),
        ]}
    if getattr(group, "name", "") == "Door swing":
        return {"type": "Door swing symbol",
                "props": [("Layer", getattr(group, "layer", "") or "")]}
    return None


#: Set at setup, so the context-menu entries can find the panel without
#: reaching through the window's internals.
_PANELS: list = []


def _remember(panel) -> None:
    _PANELS.append(panel)
