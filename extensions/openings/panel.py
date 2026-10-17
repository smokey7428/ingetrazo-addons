# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The Doors panel: the parameters of the door in front of you.

It works whether or not a door is selected, because those are the two halves of
how a door gets made:

* **nothing selected** — the panel holds the parameters the *next* door will be
  placed with, and "Place a door" hands you to the tool;
* **a door selected** — it shows that door's parameters, and changing one
  **rebuilds the door where it stands**: same opening, same wall, new
  handing or angle or size.

Every change goes through ``object.run``, so each settled change is one undo
step. Changes are coalesced on a short timer, because a spin box fires on every
arrow key and one undo step per keystroke is not what "one user action" means.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from core.i18n import current_language
from core.group import Group
from views.fold_section import FoldSection, narrow, wrapping_form

from . import object as object_mod
from . import params as params_mod

#: ``(key, label, per-metre, floor, ceiling, step)`` — the numbers a door has.
#: Sizes are shown in millimetres and stored in metres; the angle is in
#: degrees and the symbol height in metres.
NUMBERS = (
    ("width", "Width (mm)", 1000.0, 300.0, 4000.0, 10.0),
    ("height", "Height (mm)", 1000.0, 1200.0, 4000.0, 10.0),
    ("open_angle", "Open angle (°)", 1.0, 0.0, 179.0, 5.0),
    ("leaf_t", "Leaf (mm)", 1000.0, 20.0, 200.0, 1.0),
    ("frame_w", "Lining (mm)", 1000.0, 0.0, 400.0, 5.0),
    ("frame_h", "Head lining (mm)", 1000.0, 0.0, 400.0, 5.0),
    ("threshold", "Threshold (mm)", 1000.0, 0.0, 200.0, 5.0),
    ("handle", "Handle (mm)", 1000.0, 0.0, 2500.0, 10.0),
    ("symbol_z", "Symbol height (m)", 1.0, -1.0, 3.0, 0.05),
)

_TEXTS = {
    "es": {
        "Doors": "Puertas",
        "Nothing selected. These are the settings for the next door.":
            "Nada seleccionado. Estos son los ajustes de la próxima puerta.",
        "Place a door": "Colocar una puerta",
        "Erase door": "Eliminar la puerta",
        "Door": "Puerta",
        "Handing": "Mano",
        "Swing": "Apertura",
        "left": "izquierda",
        "right": "derecha",
        "in": "hacia dentro",
        "out": "hacia fuera",
        "Swing symbol": "Símbolo de barrido",
        "Frame material": "Material del marco",
        "Leaf material": "Material de la hoja",
        "Symbol layer": "Capa del símbolo",
        "Size": "Tamaño",
        "Build": "Construcción",
        "Materials": "Materiales",
        "Width (mm)": "Ancho (mm)",
        "Height (mm)": "Alto (mm)",
        "Open angle (°)": "Ángulo de apertura (°)",
        "Leaf (mm)": "Hoja (mm)",
        "Lining (mm)": "Marco (mm)",
        "Head lining (mm)": "Dintel (mm)",
        "Threshold (mm)": "Umbral (mm)",
        "Handle (mm)": "Manija (mm)",
        "Symbol height (m)": "Altura del símbolo (m)",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


class DoorsPanel(QWidget):
    """The side-tray tab. Follows the selection; edits are one undo step each."""

    def __init__(self, app) -> None:
        super().__init__()
        self._app = app
        self._dock = None
        self._tool = None
        self._door = None
        self._draft = params_mod.defaults()
        self._editors: dict = {}
        self._writing = False
        self._signature: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        self._status = QLabel()
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        row = QHBoxLayout()
        self._place = QPushButton(_t("Place a door"))
        self._place.clicked.connect(self._on_place)
        self._erase = QPushButton(_t("Erase door"))
        self._erase.clicked.connect(self._on_erase)
        row.addWidget(self._place)
        row.addWidget(self._erase)
        row.addStretch(1)
        outer.addLayout(row)
        narrow(self._place, self._erase)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._host)
        outer.addWidget(self._scroll, 1)

        # One undo step per settled change, not per arrow key.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply)

        self._build()
        app.on_document_changed(self.refresh)
        self.refresh()

    def attach_dock(self, dock) -> None:
        self._dock = dock

    def attach_tool(self, tool) -> None:
        self._tool = tool

    # ---- what is in front of the user ----
    def selected_door(self):
        scene = self._app.scene
        for entity in scene.selection:
            if isinstance(entity, Group) and object_mod.is_door(entity):
                return entity
        return None

    def show_door(self, door) -> None:
        """Select a door the extension just made, and show its parameters."""
        self._app.scene.selection = {door}
        self._door = door
        self.refresh()
        if self._dock is not None and self._dock.isVisible():
            self._app.show_panel(self._dock)

    def draft(self) -> dict:
        """The parameters a click would now use."""
        return params_mod.normalize(self._draft)

    # ---- building the form ----
    def _build(self) -> None:
        section = FoldSection(_t("Size"), "openings/size", self)
        form = wrapping_form(section.body)
        for key, label, per_metre, low, high, step in NUMBERS:
            box = QDoubleSpinBox()
            box.setRange(low, high)
            box.setDecimals(0 if per_metre > 1.0 and step >= 1.0 else 2)
            box.setSingleStep(step)
            box.valueChanged.connect(self._on_change)
            self._editors[key] = (box, per_metre)
            form.addRow(_t(label) + ":", box)
            narrow(box)
        self._host_layout.addWidget(section)

        section = FoldSection(_t("Build"), "openings/build", self)
        form = wrapping_form(section.body)
        for key, label, values in (
                ("handing", "Handing", params_mod.HANDING),
                ("swing", "Swing", params_mod.SWING)):
            box = QComboBox()
            for value in values:
                box.addItem(_t(value), value)
            box.currentIndexChanged.connect(self._on_change)
            self._editors[key] = (box, None)
            form.addRow(_t(label) + ":", box)
            narrow(box)
        self._symbol = QCheckBox(_t("Swing symbol"))
        self._symbol.toggled.connect(self._on_change)
        form.addRow(self._symbol)
        self._host_layout.addWidget(section)

        section = FoldSection(_t("Materials"), "openings/materials", self,
                              default_open=False)
        form = wrapping_form(section.body)
        for key, label in (("frame_mat", "Frame material"),
                           ("leaf_mat", "Leaf material"),
                           ("symbol_layer", "Symbol layer")):
            box = QComboBox()
            box.setEditable(True)
            box.currentIndexChanged.connect(self._on_change)
            self._editors[key] = (box, None)
            form.addRow(_t(label) + ":", box)
            narrow(box)
        self._host_layout.addWidget(section)
        self._host_layout.addStretch(1)

    def _fill_choices(self) -> None:
        """The material and layer lists come from the document, not from us."""
        scene = self._app.scene
        for key, names in (("frame_mat", sorted(scene.materials)),
                           ("leaf_mat", sorted(scene.materials)),
                           ("symbol_layer", [ly.name for ly in scene.layers])):
            box = self._editors[key][0]
            current = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItems(names)
            if current:
                box.setCurrentText(current)
            box.blockSignals(False)

    # ---- reading and writing the form ----
    def _load(self, values: dict) -> None:
        for key, (widget, per_metre) in self._editors.items():
            value = values.get(key)
            widget.blockSignals(True)
            if per_metre is not None:
                widget.setValue(float(value or 0.0) * per_metre)
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setCurrentText(str(value or ""))
            widget.blockSignals(False)
        self._symbol.blockSignals(True)
        self._symbol.setChecked(bool(values.get("symbol")))
        self._symbol.blockSignals(False)

    def _read(self) -> dict:
        values = dict(self._door is not None
                      and object_mod.door_params(self._door)
                      or self._draft)
        for key, (widget, per_metre) in self._editors.items():
            if per_metre is not None:
                values[key] = widget.value() / per_metre
            elif isinstance(widget, QComboBox):
                data = widget.currentData()
                values[key] = data if data is not None else widget.currentText()
        values["symbol"] = self._symbol.isChecked()
        return params_mod.normalize(values)

    def _on_change(self, *_args) -> None:
        if self._writing:
            return
        self._timer.start(350)

    def _apply(self) -> None:
        values = self._read()
        problems = params_mod.validate(values)
        if problems:
            self._status.setText(problems[0])
            return
        if self._door is None:
            self._draft = values               # the next door will use these
            self._status.setText(_t("Nothing selected. These are the settings "
                                    "for the next door."))
            return
        door = self._door
        self._writing = True
        try:
            object_mod.run(self._app.viewport,
                           lambda scene: object_mod.rebuild(scene, door, values))
        finally:
            self._writing = False
        self._signature = self._signature_of()
        self._refresh_status()

    # ---- following the document ----
    def _signature_of(self) -> str | None:
        door = self.selected_door()
        if door is None:
            return None
        return json.dumps(object_mod.door_params(door), sort_keys=True)

    def _refresh_status(self) -> None:
        door = self._door
        if door is None or door not in self._app.scene.groups:
            self._status.setText(_t("Nothing selected. These are the settings "
                                    "for the next door."))
            self._erase.setEnabled(False)
            self._erase.setEnabled(False)
            return
        values = object_mod.door_params(door)
        self._status.setText(f"{door.name}\n{params_mod.describe(values)}")
        self._erase.setEnabled(True)

    def refresh(self) -> None:
        """Follow the selection — but never rebuild the form out from under a
        spin box the user is in the middle of."""
        if self._writing:
            return
        door = self.selected_door()
        signature = self._signature_of()
        if door is not self._door or signature != self._signature:
            self._door = door
            self._signature = signature
            self._editors["handing"][0].blockSignals(True)
            self._fill_choices()
            self._load(object_mod.door_params(door) if door is not None
                       else self._draft)
            self._editors["handing"][0].blockSignals(False)
        self._refresh_status()

    # ---- the buttons ----
    def _on_place(self) -> None:
        from . import host
        from .tool import TOOL_KEY

        if self._tool is None or not host.activate(self._app, TOOL_KEY):
            self._status.setText(_t(
                "This IngeTrazo build does not offer the door tool. Use the "
                "menu entry instead."))
            return
        if self._dock is not None and self._dock.isVisible():
            self._app.show_panel(self._dock)

    def _on_erase(self) -> None:
        door = self._door or self.selected_door()
        if door is None:
            return
        closed: dict = {}

        def remove(scene):
            closed["ok"] = object_mod.erase(scene, door)

        self._writing = True
        try:
            object_mod.run(self._app.viewport, remove)
        finally:
            self._writing = False
        self._door = None
        self._signature = None
        self.refresh()
        if closed.get("ok") is False:
            self._app.viewport.flash_status(_t(
                "The door is gone, but its opening could not be closed — the "
                "wall was changed since. Close it by hand."), 7000)
