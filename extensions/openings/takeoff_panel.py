# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""The Take-off panel: what the model is made of.

IngeTrazo's own BIM panel cannot measure a wall of ours — it asks whether a
tagged object's face set is closed, and a wall is a stack of solids. So this
panel reads the model the way a builder prices it: every wall by skin, and every
door and window by size.

It recomputes whenever the document changes, and **Export CSV** writes the same
rows the panel shows, so what leaves the program is what you saw.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from core.i18n import current_language
from views.fold_section import FoldSection, wrapping_form

from . import schedule

_TEXTS = {
    "es": {
        "Take-off": "Metrado",
        "Walls": "Muros",
        "Openings": "Huecos",
        "Export CSV…": "Exportar CSV…",
        "Nothing to measure yet: draw a wall, or place a door or window.":
            "Todavía no hay nada que medir: dibuja un muro o coloca una puerta "
            "o ventana.",
        "Take-off — CSV (*.csv);;All files (*)":
            "Metrado — CSV (*.csv);;Todos los archivos (*)",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


class TakeoffPanel(QWidget):
    """The side-tray tab for quantities."""

    def __init__(self, app) -> None:
        super().__init__()
        self._app = app
        self._dock = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)

        self._summary = QLabel("—")
        self._summary.setWordWrap(True)
        outer.addWidget(self._summary)

        row = QHBoxLayout()
        self._export = QPushButton(_t("Export CSV…"))
        self._export.clicked.connect(self._on_export)
        row.addWidget(self._export)
        row.addStretch(1)
        outer.addLayout(row)
        self._export.setMinimumWidth(self._export.sizeHint().width())

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._host)
        outer.addWidget(self._scroll, 1)

        walls_section = FoldSection(_t("Walls"), "openings/takeoff/walls", self)
        self._walls = QLabel("—")
        self._walls.setWordWrap(False)
        wrapping_form(walls_section.body).addRow(self._walls)
        self._host_layout.addWidget(walls_section)

        openings_section = FoldSection(_t("Openings"),
                                       "openings/takeoff/openings", self)
        self._openings = QLabel("—")
        self._openings.setWordWrap(False)
        wrapping_form(openings_section.body).addRow(self._openings)
        self._host_layout.addWidget(openings_section)
        self._host_layout.addStretch(1)

        app.on_document_changed(self.refresh)
        self.refresh()

    def attach_dock(self, dock) -> None:
        self._dock = dock

    # ---- what the model is made of ----
    def data(self) -> dict:
        return schedule.rows(self._app.scene)

    def refresh(self) -> None:
        data = self.data()
        if not data["walls"] and not data["openings"]:
            self._summary.setText(_t("Nothing to measure yet: draw a wall, or "
                                     "place a door or window."))
            self._walls.setText("—")
            self._openings.setText("—")
            return
        self._summary.setText(schedule.summary(data))
        self._walls.setText(schedule.wall_lines(data))
        self._openings.setText(schedule.opening_lines(data))

    # ---- out ----
    def _on_export(self) -> None:
        from views.filedialogs import file_dialogs

        path, _filter = file_dialogs.getSaveFileName(
            self.window(), _t("Take-off"), "takeoff.csv",
            _t("Take-off — CSV (*.csv);;All files (*)"))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(schedule.csv(self.data()))
        except OSError as exc:
            self._app.viewport.flash_status(f"Take-off: {exc}", 6000)
            return
        self._app.viewport.flash_status(
            _t("Wrote {path}", path=path), 4000)


__all__ = ["TakeoffPanel"]
