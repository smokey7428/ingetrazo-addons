# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""The Walls panel: configure a wall, then draw it.

Two halves, like the openings panel:

* **nothing selected** — the build-up the *next* wall will be drawn with:
  a type from the catalogue, and its skins, each with a name, a thickness and a
  material. "Draw a wall" hands you to the tool, which is where the polyline
  happens;
* **a wall selected** — that wall's build-up, and changing it regenerates the
  wall where it stands.

A **skin** is one layer of the build-up — buitenblad, isolatie, binnenblad — and
the wall is centred on the line it is drawn along, so the skins sit half on
either side of it. The list reads from the outside in, and it is the list that
makes a multi-skin wall possible: add, remove, retype, reorder by retyping.

Every change is one undo step, coalesced on a short timer so a spin box does not
write one step per arrow key.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from core.group import Group
from core.i18n import current_language
from views.fold_section import FoldSection, narrow, wrapping_form

from . import library
from . import object as object_mod
from . import profiles
from . import wall_object as wall_obj
from . import walls

#: Where the panel remembers the two choices. A preference of the person, not a
#: property of the document: two users of one model may want different words.
SETTINGS_LANGUAGE = "openings/wall/language"
SETTINGS_LIBRARY = "openings/wall/library"

#: A language, named in that language — the only readable way to offer a list of
#: languages to somebody who does not read the one the interface is in.
LANGUAGE_NAMES = {
    "nl": "Nederlands",
    "en-GB": "English (UK)",
    "de": "Deutsch",
    "es-ES": "Español (España)",
    "es-PE": "Español (Perú)",
}

_TEXTS = {
    "es": {
        "Walls": "Muros",
        "Wall": "Muro",
        "Type": "Modelo",
        "Skin": "Capa",
        "Skins": "Capas",
        "Thickness (mm)": "Espesor (mm)",
        "Material": "Material",
        "Height (mm)": "Alto (mm)",
        "Draw a wall": "Dibujar un muro",
        "Erase": "Eliminar",
        "Add a skin": "Añadir una capa",
        "Remove": "Quitar",
        "Nothing selected. These are the skins of the next wall.":
            "Nada seleccionado. Estas son las capas del próximo muro.",
        "Centred on the line you draw: {t} mm in all.":
            "Centrado en la línea que dibujas: {t} mm en total.",
        "Language": "Idioma",
        "Library": "Biblioteca",
        "Search": "Buscar",
        "Search in every language…": "Buscar en todos los idiomas…",
        "{n} layers": "{n} capas",
        "draft": "borrador",
        "reviewed": "revisado",
        "yours": "tuyo",
        "A role's name follows the language you are working in.":
            "El nombre de un rol sigue el idioma en el que trabajas.",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


class WallsPanel(QWidget):
    """The side-tray tab for walls of our own."""

    def __init__(self, app) -> None:
        super().__init__()
        self._app = app
        self._dock = None
        self._tool = None
        self._wall = None
        self._draft = {}
        self._writing = False
        self._signature: str | None = None
        self._skin_rows: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)

        self._status = QLabel()
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # ---- which words, and which country's walls ----
        # Two settings, not one: a Dutch office on a project in Peru wants Dutch
        # menus and Peruvian walls, and IngeTrazo has no Dutch to offer either.
        self._settings = QSettings()
        codes = library.languages() or ("nl",)
        self._language = str(self._settings.value(SETTINGS_LANGUAGE, "")
                             or library.default_language(current_language()))
        self._library = str(self._settings.value(SETTINGS_LIBRARY, ""))
        if self._library not in codes:
            self._library = (self._language if self._language in codes
                             else codes[0])
        self._draft = walls.defaults(language=self._language)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Language") + ":"))
        self._language_box = QComboBox()
        # Every language we have words for, not only the ones a library exists
        # in: a Dutch build-up read by an English user is read in English, and
        # a library that ships later must not be needed to offer the words.
        for code in library.LOCALES:
            self._language_box.addItem(LANGUAGE_NAMES.get(code, code), code)
        self._language_box.setCurrentIndex(
            max(0, self._language_box.findData(self._language)))
        self._language_box.currentIndexChanged.connect(self._on_language)
        row.addWidget(self._language_box, 1)
        outer.addLayout(row)
        narrow(self._language_box)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Library") + ":"))
        self._library_box = QComboBox()
        for code in codes:
            self._library_box.addItem(code, code)
        self._library_box.setCurrentIndex(
            max(0, self._library_box.findData(self._library)))
        self._library_box.currentIndexChanged.connect(self._on_library)
        row.addWidget(self._library_box, 1)
        outer.addLayout(row)
        narrow(self._library_box)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Search") + ":"))
        self._search = QLineEdit()
        self._search.setPlaceholderText(_t("Search in every language…"))
        self._search.textChanged.connect(self._on_search)
        row.addWidget(self._search, 1)
        outer.addLayout(row)
        narrow(self._search)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Type") + ":"))
        self._type = QComboBox()
        self._type.currentIndexChanged.connect(self._on_type)
        row.addWidget(self._type, 1)
        outer.addLayout(row)
        narrow(self._type)

        self._about = QLabel()
        self._about.setWordWrap(True)
        outer.addWidget(self._about)

        row = QHBoxLayout()
        self._draw = QPushButton(_t("Draw a wall"))
        self._draw.clicked.connect(self._on_draw)
        self._erase = QPushButton(_t("Erase"))
        self._erase.clicked.connect(self._on_erase)
        row.addWidget(self._draw)
        row.addWidget(self._erase)
        row.addStretch(1)
        outer.addLayout(row)
        # Not `narrow()`: in a row with a stretch it squeezes a button to a
        # 40 px sliver. A button in a button row wants its own size.
        for button in (self._draw, self._erase):
            button.setMinimumWidth(button.sizeHint().width())

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._host)
        outer.addWidget(self._scroll, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply)

        self._build(self._draft)
        self.reload_types(keep=self._draft.get("type"))
        app.on_document_changed(self.refresh)
        self.refresh()

    def attach_dock(self, dock) -> None:
        self._dock = dock

    def attach_tool(self, tool) -> None:
        self._tool = tool

    # ---- the library, and the language it is read in ----
    def library_code(self) -> str:
        """Which country's walls this panel is offering."""
        return self._library

    def language_code(self) -> str:
        """Which language the panel is naming them in."""
        return self._language

    def reload_types(self, keep: str | None = None) -> None:
        """Offer the walls of the chosen library, filtered by the search box.

        Public, because **importing** a wall type has to rebuild this list: an
        imported type is drawn with in the same session, not after a restart.
        """
        if getattr(self, "_type", None) is None:
            return
        wanted = keep if keep is not None else self._type.currentData()
        entries = library.search(self._library, self._search.text(),
                                 self._language)
        self._type.blockSignals(True)
        try:
            self._type.clear()
            for entry in entries:
                self._type.addItem(self._item_text(entry), entry["key"])
            index = self._type.findData(wanted) if wanted else -1
            self._type.setCurrentIndex(index if index >= 0
                                       else (0 if entries else -1))
        finally:
            self._type.blockSignals(False)
        self._show_about(self._current_entry())

    def _item_text(self, entry: dict) -> str:
        """One line that answers the only three questions worth asking of a
        wall type: what it is, how thick it is, and whether anyone has checked
        it."""
        name = library.wall_name(entry, self._language)
        total = sum(skin["thickness"] for skin in entry["skins"]) * 1000.0
        bits = [f"{total:.0f} mm"]
        if len(entry["skins"]) > 1:
            bits.append(_t("{n} layers", n=len(entry["skins"])))
        bits.append(_t("reviewed") if entry["reviewed"] else _t("draft"))
        if entry.get("mine"):
            bits.append(_t("yours"))
        return f"{name} — " + " · ".join(bits)

    def _current_entry(self):
        key = self._type.currentData() if getattr(self, "_type", None) else None
        return library.wall(key, self._library) if key else None

    def _show_about(self, entry) -> None:
        """The flags under the picker, with the source kept as a tooltip: a
        build-up that came from somewhere says so, without shouting."""
        label = getattr(self, "_about", None)
        if label is None:
            return
        if entry is None:
            label.setText("")
            label.setToolTip("")
            return
        bits = [_t("reviewed") if entry["reviewed"] else _t("draft")]
        if entry.get("mine"):
            bits.append(_t("yours"))
        bits.append(entry["locale"])
        label.setText(" · ".join(bits))
        label.setToolTip(entry.get("source") or "")

    def _on_language(self, _index: int = 0) -> None:
        code = self._language_box.currentData()
        if not code or code == self._language:
            return
        self._language = str(code)
        self._settings.setValue(SETTINGS_LANGUAGE, self._language)
        self.reload_types()
        self._redraw()

    def _on_library(self, _index: int = 0) -> None:
        code = self._library_box.currentData()
        if not code or code == self._library:
            return
        self._library = str(code)
        self._settings.setValue(SETTINGS_LIBRARY, self._library)
        self.reload_types()
        self._redraw()

    def _on_search(self, _text: str = "") -> None:
        self.reload_types(keep=self._draft.get("type"))

    def _redraw(self) -> None:
        """Put what is on screen into the language now chosen.

        The *draft* is taken again from the library, so its layers arrive named
        in that language. A selected wall is only re-rendered: choosing a
        language is not an edit, and must never write to the document.
        """
        if self._wall is None:
            key = self._type.currentData() or self._draft.get("type")
            self._draft = walls.defaults(key, self._language)
            self._build(self._draft)
            self._fill_materials()
            self._load(self._draft)
            self._show_about(self._current_entry())
            return
        self._signature = None
        self.refresh()

    # ---- what is in front of the user ----
    def selected(self):
        scene = self._app.scene
        for entity in scene.selection:
            if isinstance(entity, Group) and wall_obj.is_wall(entity):
                return entity
        return None

    def show_wall(self, wall) -> None:
        self._app.scene.selection = {wall}
        self._wall = wall
        self.refresh()
        if self._dock is not None and self._dock.isVisible():
            self._app.show_panel(self._dock)

    def draft(self) -> dict:
        """The parameters the tool will draw with."""
        return walls.normalize(self._draft)

    # ---- the form ----
    def _build(self, w: dict) -> None:
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._skin_rows = []

        section = FoldSection(_t("Skins"), "openings/wall/skins", self)
        self._skins_layout = QVBoxLayout(section.body)
        self._skins_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.addWidget(section)

        for index, skin in enumerate(w["skins"]):
            self._add_skin_row(index, skin)
        row = QHBoxLayout()
        add = QPushButton(_t("Add a skin"))
        add.clicked.connect(self._on_add_skin)
        row.addWidget(add)
        row.addStretch(1)
        self._skins_layout.addLayout(row)
        for button in (add,):
            button.setMinimumWidth(button.sizeHint().width())

        section = FoldSection(_t("Size"), "openings/wall/size", self)
        form = wrapping_form(section.body)
        self._height = QDoubleSpinBox()
        self._height.setRange(300.0, 12000.0)
        self._height.setDecimals(0)
        self._height.setSingleStep(50.0)
        self._height.valueChanged.connect(self._on_change)
        form.addRow(_t("Height (mm)") + ":", self._height)
        narrow(self._height)
        self._host_layout.addWidget(section)

        section = FoldSection(_t("Quantities"), "openings/wall/quantities",
                              self, default_open=False)
        form = wrapping_form(section.body)
        self._quantities = QLabel("—")
        self._quantities.setWordWrap(True)
        form.addRow(self._quantities)
        self._host_layout.addWidget(section)
        self._host_layout.addStretch(1)

    def _add_skin_row(self, index: int, skin: dict) -> None:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)

        role = str(skin.get("role") or "")
        name = QLineEdit(str(skin.get("name", "")))
        if role:
            # A layer's name is a **translation** of its role, so it is not the
            # user's to type: show the role in the language being worked in,
            # and keep the field for a layer that has no role.
            label = library.role_label(role, self._language)
            if label:
                name.setText(label)
            name.setReadOnly(True)
            name.setToolTip(_t("A role's name follows the language you are "
                               "working in."))
        else:
            name.editingFinished.connect(self._on_change)
        line.addWidget(name, 2)

        thickness = QDoubleSpinBox()
        thickness.setRange(10.0, 500.0)
        thickness.setDecimals(0)
        thickness.setSingleStep(5.0)
        thickness.setValue(float(skin.get("thickness", 0.1)) * 1000.0)
        thickness.valueChanged.connect(self._on_change)
        line.addWidget(thickness, 1)

        material = QComboBox()
        material.setEditable(True)
        material.addItems(sorted(self._app.scene.materials))
        material.setCurrentText(str(skin.get("material", "Wall")))
        material.currentIndexChanged.connect(self._on_change)
        line.addWidget(material, 1)

        drop = QPushButton("×")
        drop.setToolTip(_t("Remove"))
        drop.clicked.connect(lambda _c=False, i=index: self._on_remove_skin(i))
        line.addWidget(drop)
        for box in (thickness, material):
            narrow(box)

        self._skins_layout.addWidget(row)
        self._skin_rows.append((name, thickness, material))

    def _fill_materials(self) -> None:
        names = sorted(self._app.scene.materials)
        for _name, _thickness, material in self._skin_rows:
            current = material.currentText()
            material.blockSignals(True)
            material.clear()
            material.addItems(names)
            if current:
                material.setCurrentText(current)
            material.blockSignals(False)

    def _load(self, w: dict) -> None:
        self._writing = True
        try:
            index = self._type.findData(w["type"])
            self._type.blockSignals(True)
            self._type.setCurrentIndex(max(index, 0))
            self._type.blockSignals(False)
            self._height.blockSignals(True)
            self._height.setValue(float(w["height"]) * 1000.0)
            self._height.blockSignals(False)
        finally:
            self._writing = False

    def _read(self) -> dict:
        base = dict(wall_obj.wall_params(self._wall) if self._wall is not None
                    else self._draft)
        base["type"] = self._type.currentData() or base["type"]
        base["height"] = self._height.value() / 1000.0
        skins = []
        for name, thickness, material in self._skin_rows:
            skins.append({
                "name": name.text().strip(),
                "thickness": thickness.value() / 1000.0,
                "material": material.currentText().strip() or "Wall",
            })
        base["skins"] = skins
        return walls.normalize(base)

    # ---- the buttons and the numbers ----
    def _on_type(self, _index: int) -> None:
        """Choosing a build-up takes its skins — that is what a type *is*."""
        if self._writing:
            return
        name = self._type.currentData()
        if not name:
            return
        fresh = walls.defaults(name, self._language)
        fresh["height"] = self._height.value() / 1000.0
        if self._wall is not None:
            fresh["path"] = wall_obj.wall_params(self._wall).get("path") or []
        self._build(fresh)
        self._load(fresh)
        self._fill_materials()
        self._show_about(self._current_entry())
        self._commit(fresh)

    def _on_add_skin(self) -> None:
        w = self._read()
        w["skins"].append({"name": f"Skin {len(w['skins']) + 1}",
                           "thickness": 0.05, "material": "Wall"})
        self._build(w)
        self._fill_materials()
        self._commit(w)

    def _on_remove_skin(self, index: int) -> None:
        w = self._read()
        if 0 <= index < len(w["skins"]) and len(w["skins"]) > 1:
            w["skins"].pop(index)
            self._build(w)
            self._fill_materials()
            self._commit(w)

    def _on_change(self, *_args) -> None:
        if self._writing:
            return
        self._timer.start(350)

    def _apply(self) -> None:
        self._commit(self._read())

    def _commit(self, w: dict) -> None:
        w = walls.normalize(w)
        if self._wall is None:
            # A draft is a build-up, not a placed wall, so it has no path yet.
            # Requiring two points of it meant every type picked in the panel
            # was refused in silence, and the tool drew the type that had been
            # there before.
            problems = walls.validate(w, placed=False)
            if problems:
                self._status.setText(problems[0])
                return
            self._draft = w
            self._refresh_status()
            return
        problems = walls.validate(w)
        if problems:
            self._status.setText(problems[0])
            return
        wall = self._wall
        self._writing = True
        try:
            object_mod.run(self._app.viewport,
                           lambda scene: wall_obj.regenerate(scene, wall, w),
                           label="Wall")
        finally:
            self._writing = False
        self._signature = self._signature_of()
        self._refresh_status()

    # ---- following the document ----
    def _signature_of(self) -> str | None:
        wall = self.selected()
        if wall is None:
            return None
        return json.dumps(wall_obj.wall_params(wall), sort_keys=True)

    def _refresh_status(self) -> None:
        wall = self._wall
        if wall is None or wall not in self._app.scene.groups:
            self._status.setText(_t("Nothing selected. These are the skins of "
                                    "the next wall."))
            self._erase.setEnabled(False)
            return
        w = wall_obj.wall_params(wall)
        self._status.setText(f"{wall.name}\n{walls.describe(w)}")
        self._erase.setEnabled(True)
        self._show_quantities(w)

    def _show_quantities(self, w: dict) -> None:
        """Per skin: the wall face a builder prices, its volume and its mass.

        A composite wall is a stack of solids, so this — not one number for
        "the wall" — is what a take-off wants: m² of brick, m² of insulation,
        m³ of block.
        """
        label = getattr(self, "_quantities", None)
        if label is None:
            return
        lines = []
        for row in wall_obj.quantities(w):
            mass = (f" · {row['mass']:.0f} kg" if row["mass"] else "")
            lines.append(f"{row['name']}: {row['area']:.2f} m² · "
                         f"{row['volume']:.3f} m³{mass}")
        label.setText("\n".join(lines) or "—")

    def refresh(self) -> None:
        if self._writing:
            return
        wall = self.selected()
        signature = self._signature_of()
        if wall is not self._wall or signature != self._signature:
            self._wall = wall
            self._signature = signature
            w = wall_obj.wall_params(wall) if wall is not None else self._draft
            self._build(w)
            self._fill_materials()
            self._load(w)
        self._refresh_status()

    # ---- the buttons ----
    def _on_draw(self) -> None:
        from . import host
        from .wall_tool import TOOL_KEY

        if self._tool is None or not host.activate(self._app, TOOL_KEY):
            self._status.setText(_t(
                "This IngeTrazo build does not offer the wall tool."))
            return
        if self._dock is not None and self._dock.isVisible():
            self._app.show_panel(self._dock)

    def _on_erase(self) -> None:
        wall = self._wall or self.selected()
        if wall is None:
            return
        self._writing = True
        try:
            object_mod.run(self._app.viewport,
                           lambda scene: wall_obj.erase(scene, wall),
                           label="Wall")
        finally:
            self._writing = False
        self._wall = None
        self._signature = None
        self.refresh()
