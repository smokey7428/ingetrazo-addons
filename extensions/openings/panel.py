# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""The Openings panel: the parameters of the door or window in front of you.

It works whether or not something is selected, because those are the two halves
of how an opening gets made:

* **nothing selected** — the panel holds the parameters the *next* opening will
  be placed with, and "Place" hands you to the tool;
* **something selected** — it shows that opening's parameters, and changing one
  **rebuilds it where it stands**: same opening, same wall, new handing or
  angle or size.

The **kind and type** come first, above the scrolled form, because they decide
which fields exist: a window has a sill, a sash and glazing, and a door has a
leaf, a threshold and a handle. Choosing a type takes its sizes and sections
from :mod:`openings.profiles` — the Dutch standards — so switching to a
draairaam sets 54 × 67 raamhout and 20 mm glass for you.

Every change goes through ``object.run``, so each settled change is one undo
step. Changes are coalesced on a short timer, because a spin box fires on every
arrow key and one undo step per keystroke is not what "one user action" means.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from core.i18n import current_language
from core.group import Group
from views.fold_section import FoldSection, narrow, wrapping_form

from . import object as object_mod
from . import params as params_mod
from . import profiles

#: Every number an opening can have: ``(label, per-metre, floor, ceiling,
#: step)``. Sizes are shown in millimetres and stored in metres; the angle is
#: in degrees and the symbol height in metres.
NUMBERS = {
    "width": ("Width (mm)", 1000.0, 300.0, 6000.0, 10.0),
    "height": ("Height (mm)", 1000.0, 300.0, 6000.0, 10.0),
    "sill": ("Sill above the floor (mm)", 1000.0, 0.0, 4000.0, 10.0),
    "open_angle": ("Open angle (°)", 1.0, 0.0, 179.0, 5.0),
    "leaf_t": ("Leaf (mm)", 1000.0, 0.0, 200.0, 1.0),
    "frame_w": ("Frame section (mm)", 1000.0, 0.0, 400.0, 1.0),
    "frame_h": ("Head section (mm)", 1000.0, 0.0, 400.0, 1.0),
    "frame_b": ("Bottom section (mm)", 1000.0, 0.0, 400.0, 1.0),
    "frame_depth": ("Frame depth (mm)", 1000.0, 0.0, 600.0, 1.0),
    "sash_w": ("Sash section (mm)", 1000.0, 0.0, 200.0, 1.0),
    "sash_d": ("Sash depth (mm)", 1000.0, 0.0, 200.0, 1.0),
    "glass_t": ("Glass (mm)", 1000.0, 0.0, 60.0, 1.0),
    "threshold": ("Threshold (mm)", 1000.0, 0.0, 200.0, 5.0),
    "handle": ("Handle (mm)", 1000.0, 0.0, 2500.0, 10.0),
    "handle_len": ("Handle reach (mm)", 1000.0, 0.0, 400.0, 5.0),
    "symbol_z": ("Symbol height (m)", 1.0, -1.0, 3.0, 0.05),
}

#: Which fields each kind shows, in the order they are read. What is not here
#: is not offered: a door has no sash, and a window has no threshold.
FIELDS = {
    "door": ("width", "height", "open_angle", "leaf_t", "frame_w", "frame_h",
             "frame_depth", "threshold", "handle", "handle_len"),
    "window": ("width", "height", "sill", "frame_w", "frame_h", "frame_b",
               "frame_depth", "sash_w", "sash_d", "glass_t"),
}

#: What a field means, where the label cannot say it all.
TIPS = {
    "frame_depth": "How deep the frame section runs into the wall. The "
                    "standard kozijn is 114 mm; 0 makes the frame fill the "
                    "whole reveal instead.",
    "sash_w": "The face width of the sash that opens — raamhout is 54 mm.",
    "sash_d": "How deep the sash is — raamhout is 67 mm.",
    "sill": "How far the opening stands above the floor: 900 mm is a "
            "window, 0 is a door.",
    "open_angle": "How far the panel stands open, and the arc drawn in the "
                   "plan.",
}

_TEXTS = {
    "es": {
        "Openings": "Huecos",
        "Door": "Puerta",
        "Window": "Ventana",
        "Kind": "Tipo",
        "Type": "Modelo",
        "Nothing selected. These are the settings for the next one.":
            "Nada seleccionado. Estos son los ajustes del próximo.",
        "Place": "Colocar",
        "Erase": "Eliminar",
        "Handing": "Mano",
        "Swing": "Apertura",
        "left": "izquierda",
        "right": "derecha",
        "in": "hacia dentro",
        "out": "hacia fuera",
        "Swing symbol": "Símbolo de barrido",
        "Size": "Tamaño",
        "Build": "Construcción",
        "Materials": "Materiales",
        "Frame material": "Material del marco",
        "Panel material": "Material de la hoja",
        "Glass material": "Material del vidrio",
        "Width (mm)": "Ancho (mm)",
        "Height (mm)": "Alto (mm)",
        "Sill above the floor (mm)": "Antepecho (mm)",
        "Open angle (°)": "Ángulo de apertura (°)",
        "Leaf (mm)": "Hoja (mm)",
        "Frame section (mm)": "Sección del marco (mm)",
        "Head section (mm)": "Sección del dintel (mm)",
        "Bottom section (mm)": "Sección inferior (mm)",
        "Frame depth (mm)": "Fondo del marco (mm)",
        "Sash section (mm)": "Sección del batiente (mm)",
        "Sash depth (mm)": "Fondo del batiente (mm)",
        "Glass (mm)": "Vidrio (mm)",
        "Threshold (mm)": "Umbral (mm)",
        "Handle (mm)": "Manija (mm)",
        "Handle reach (mm)": "Saliente de la manija (mm)",
        "Symbol height (m)": "Altura del símbolo (m)",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


class OpeningsPanel(QWidget):
    """The side-tray tab. Follows the selection; edits are one undo step each."""

    def __init__(self, app) -> None:
        super().__init__()
        self._app = app
        self._dock = None
        self._tool = None
        self._item = None
        self._draft = params_mod.defaults()
        self._editors: dict = {}
        self._writing = False
        self._signature: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)

        self._status = QLabel()
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # Kind and type sit outside the scrolled form: they survive the form
        # being rebuilt when the kind changes, which is the whole point of
        # putting them here.
        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Kind") + ":"))
        self._kind = QComboBox()
        for kind in params_mod.KINDS:
            self._kind.addItem(_t("Window" if kind == "window" else "Door"),
                               kind)
        self._kind.currentIndexChanged.connect(self._on_kind)
        row.addWidget(self._kind, 1)
        outer.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Type") + ":"))
        self._type = QComboBox()
        self._type.currentIndexChanged.connect(self._on_type)
        row.addWidget(self._type, 1)
        outer.addLayout(row)
        narrow(self._kind, self._type)

        row = QHBoxLayout()
        self._place = QPushButton(_t("Place"))
        self._place.clicked.connect(self._on_place)
        self._erase = QPushButton(_t("Erase"))
        self._erase.clicked.connect(self._on_erase)
        row.addWidget(self._place)
        row.addWidget(self._erase)
        row.addStretch(1)
        outer.addLayout(row)
        # NOT `narrow()`: it sets the horizontal size policy to Ignored, and in
        # a row *with* a stretch that squeezes a button down to the 40 px
        # minimum it also sets — a sliver reading "P…", which is why these were
        # invisible. `narrow()` is for controls that must shrink with the tray
        # (combos, spin boxes); a button in a button row wants its own size.
        for button in (self._place, self._erase):
            button.setMinimumWidth(button.sizeHint().width())

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

        self._build_form(self._draft["kind"])
        app.on_document_changed(self.refresh)
        self.refresh()

    def attach_dock(self, dock) -> None:
        self._dock = dock

    def attach_tool(self, tool) -> None:
        self._tool = tool

    # ---- what is in front of the user ----
    def selected(self):
        scene = self._app.scene
        for entity in scene.selection:
            if isinstance(entity, Group) and object_mod.is_opening(entity):
                return entity
        return None

    def show_opening(self, item) -> None:
        """Select what the extension just made, and show its parameters."""
        self._app.scene.selection = {item}
        self._item = item
        self.refresh()
        if self._dock is not None and self._dock.isVisible():
            self._app.show_panel(self._dock)

    def draft(self) -> dict:
        """The parameters a click would now use."""
        return params_mod.normalize(self._draft)

    # ---- the form ----
    def _build_form(self, kind: str) -> None:
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._editors = {}

        section = FoldSection(_t("Size"), "openings/size", self)
        form = wrapping_form(section.body)
        for key in FIELDS.get(kind, FIELDS["door"]):
            label, per_metre, low, high, step = NUMBERS[key]
            box = QDoubleSpinBox()
            box.setRange(low, high)
            box.setDecimals(0 if step >= 1.0 else 2)
            box.setSingleStep(step)
            box.valueChanged.connect(self._on_change)
            if key in TIPS:
                box.setToolTip(TIPS[key])
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
        for key in ("frame_mat", "leaf_mat", "glass_mat"):
            if key == "glass_mat" and kind != "window":
                continue
            box = QComboBox()
            box.setEditable(True)
            box.currentIndexChanged.connect(self._on_change)
            self._editors[key] = (box, None)
            form.addRow(_t({"frame_mat": "Frame material",
                            "leaf_mat": "Panel material",
                            "glass_mat": "Glass material"}[key]) + ":", box)
            narrow(box)
        self._host_layout.addWidget(section)
        self._host_layout.addStretch(1)
        self._fill_choices()

    def _fill_choices(self) -> None:
        """The material lists come from the document, not from us."""
        names = sorted(self._app.scene.materials)
        for key in ("frame_mat", "leaf_mat", "glass_mat"):
            editor = self._editors.get(key)
            if editor is None:
                continue
            box = editor[0]
            current = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItems(names)
            if current:
                box.setCurrentText(current)
            box.blockSignals(False)

    def _fill_types(self, kind: str, keep: str | None) -> None:
        self._type.blockSignals(True)
        self._type.clear()
        for name in profiles.names(kind):
            self._type.addItem(profiles.label(kind, name), name)
        index = self._type.findData(keep) if keep else 0
        self._type.setCurrentIndex(max(index, 0))
        self._type.blockSignals(False)

    # ---- reading and writing ----
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
        values = dict(object_mod.opening_params(self._item)
                      if self._item is not None else self._draft)
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

    def _on_kind(self, _index: int) -> None:
        """Switching kind takes the new kind's own type and sizes — a window is
        not a door with different numbers anywhere it matters — and **converts
        the opening in front of you**, like every other field here. One undo
        step away if it was not what you meant."""
        if self._writing:
            return
        kind = self._kind.currentData() or "door"
        fresh = params_mod.defaults(kind)
        self._fill_types(kind, fresh["type"])
        self._build_form(kind)
        self._commit(fresh)

    def _on_type(self, _index: int) -> None:
        if self._writing:
            return
        kind = self._kind.currentData() or "door"
        name = self._type.currentData()
        if not name:
            return
        fresh = params_mod.defaults(kind, name)
        # The opening's size is the user's to keep: a type decides the sections
        # and what moves, not how big the hole in the wall is.
        current = self._read()
        fresh["width"] = current["width"]
        fresh["height"] = current["height"]
        if kind == "window":
            fresh["sill"] = current["sill"]
        self._commit(fresh)

    def _commit(self, values: dict) -> None:
        """Put ``values`` in the form and write them: to the selected opening,
        or to the settings for the next one."""
        values = params_mod.normalize(values)
        problems = params_mod.validate(values)
        if problems:
            self._status.setText(problems[0])
            return
        self._writing = True
        try:
            self._load(values)
        finally:
            self._writing = False
        if self._item is None:
            self._draft = values
            self._refresh_status()
            return
        item = self._item
        self._writing = True
        try:
            object_mod.run(self._app.viewport,
                           lambda scene: object_mod.rebuild(scene, item,
                                                            values))
        finally:
            self._writing = False
        self._signature = self._signature_of()
        self._refresh_status()

    def _apply(self) -> None:
        values = self._read()
        problems = params_mod.validate(values)
        if problems:
            self._status.setText(problems[0])
            return
        self._commit(values)

    # ---- following the document ----
    def _signature_of(self) -> str | None:
        item = self.selected()
        if item is None:
            return None
        return json.dumps(object_mod.opening_params(item), sort_keys=True)

    def _refresh_status(self) -> None:
        item = self._item
        if item is None or item not in self._app.scene.groups:
            self._status.setText(_t("Nothing selected. These are the settings "
                                    "for the next one."))
            self._erase.setEnabled(False)
            return
        values = object_mod.opening_params(item)
        self._status.setText(f"{item.name}\n{params_mod.describe(values)}")
        self._erase.setEnabled(True)

    def refresh(self) -> None:
        """Follow the selection — but never rebuild the form out from under a
        spin box the user is in the middle of."""
        if self._writing:
            return
        item = self.selected()
        signature = self._signature_of()
        if item is not self._item or signature != self._signature:
            self._item = item
            self._signature = signature
            values = (object_mod.opening_params(item) if item is not None
                      else self._draft)
            self._writing = True                 # not a user's change
            try:
                self._kind.blockSignals(True)
                index = self._kind.findData(values["kind"])
                self._kind.setCurrentIndex(max(index, 0))
                self._kind.blockSignals(False)
                self._fill_types(values["kind"], values["type"])
                if item is None or set(FIELDS[values["kind"]]) != set(
                        k for k, _v in self._editors.items()):
                    self._build_form(values["kind"])
                self._load(values)
            finally:
                self._writing = False
        self._refresh_status()

    # ---- the buttons ----
    def _on_place(self) -> None:
        from . import host
        from .tool import TOOL_KEY

        if self._tool is None or not host.activate(self._app, TOOL_KEY):
            self._status.setText(_t(
                "This IngeTrazo build does not offer the tool. Use the menu "
                "entry instead."))
            return
        if self._dock is not None and self._dock.isVisible():
            self._app.show_panel(self._dock)

    def _on_erase(self) -> None:
        item = self._item or self.selected()
        if item is None:
            return
        closed: dict = {}

        def remove(scene):
            closed["ok"] = object_mod.erase(scene, item)

        self._writing = True
        try:
            object_mod.run(self._app.viewport, remove)
        finally:
            self._writing = False
        self._item = None
        self._signature = None
        self.refresh()
        if closed.get("ok") is False:
            self._app.viewport.flash_status(_t(
                "It is gone, but its opening could not be closed — the wall "
                "was changed since. Close it by hand."), 7000)
