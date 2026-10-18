# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Smoke test for this project's extension setup — tested with IngeTrazo 0.5.8.

Proves end to end that:
  * a ``Tool`` subclass in ``extensions/`` shows up in the Extensions menu;
  * ``setup(app)`` runs, a side-tray panel is added and an Extensions-menu
    action brings it back to the front;
  * document data survives a save/reopen of the .igz;
  * reading the model works (``scene.loose_mesh`` / ``scene.groups``).

Safe to delete once a real extension exists: it only reads the document and
counts.

Install: ``./dev/install.sh`` then restart IngeTrazo.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QFormLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from core.i18n import current_language
from tools.base import Tool

# English is the source language; a missing entry falls back to it.
_TEXTS = {
    "es": {
        "Hello IngeTrazo": "Hola IngeTrazo",
        "Hello, IngeTrazo!": "¡Hola, IngeTrazo!",
        "Model counts": "Recuento del modelo",
        "Refresh": "Actualizar",
        "Groups: {n}": "Grupos: {n}",
        "Faces: {n}": "Caras: {n}",
        "Edges: {n}": "Aristas: {n}",
        "This panel is drawn by hello_ingetrazo.py.":
            "Este panel lo dibuja hello_ingetrazo.py.",
        "Opens the panel and counts the model.":
            "Abre el panel y cuenta el modelo.",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


def _counts(scene) -> dict:
    """Vertices/edges/faces over the loose mesh and every placed group.

    ``scene.loose_mesh`` and not ``scene.mesh``: the latter is swapped while a
    group is open for editing, so totals read from it are wrong.
    """
    from core.group import iter_placements

    loose = scene.loose_mesh
    placed = [(g, m) for group in scene.groups
              for g, m in iter_placements(group)]
    return {
        "groups": len(scene.groups),
        "faces": len(loose.faces) + sum(len(g.mesh.faces) for g, _m in placed),
        "edges": len(loose.edges) + sum(len(g.mesh.edges) for g, _m in placed),
    }


class HelloIngeTrazoTool(Tool):
    """The menu entry: a one-shot tool, it does not become the active tool."""

    name = "Hello IngeTrazo"
    shortcut = None
    description = "Opens the panel and counts the model."

    def on_activate(self, viewport):
        viewport.flash_status(_t("Hello, IngeTrazo!"), 3000)

    def on_deactivate(self, viewport):
        pass


class Panel(QWidget):
    """The side-tray tab: what the extension keeps open while modelling."""

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._labels = {}

        box = QVBoxLayout(self)
        form = QFormLayout()
        for key in ("groups", "faces", "edges"):
            label = QLabel("—")
            self._labels[key] = label
            form.addRow(_t("Model counts") + f" — {key}", label)
        box.addLayout(form)

        refresh = QPushButton(_t("Refresh"))
        refresh.clicked.connect(self.refresh)
        box.addWidget(refresh)

        note = QLabel(_t("This panel is drawn by hello_ingetrazo.py."))
        note.setWordWrap(True)
        box.addWidget(note)
        box.addStretch(1)

        app.on_document_changed(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            counts = _counts(self._app.scene)
        except Exception:                      # noqa: BLE001 — never break the UI
            return
        for key, value in counts.items():
            self._labels[key].setText(_t("Groups: {n}", n=value)
                                      if key == "groups"
                                      else _t("Faces: {n}", n=value)
                                      if key == "faces"
                                      else _t("Edges: {n}", n=value))


def setup(app):
    """Called once when the main window is built (API_VERSION 2)."""
    dock = app.add_panel("Hello", Panel(app))

    # Document data: ONE JSON-safe value per extension, saved in the .igz.
    opened = (app.document_data(default={"opened": 0}) or {}).get("opened", 0)
    app.set_document_data({"opened": opened + 1})

    app.add_menu_action(_t("Hello IngeTrazo"), lambda: app.show_panel(dock),
                        shortcut=None, tip=_t("Opens the panel and counts "
                                              "the model."))
