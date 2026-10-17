# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The IFC panel: every field of the selected element, editable.

It follows the selection — pick a tagged group or tagged faces and its IFC
record appears here — because the point is to look at the model and correct
its data, not to open a form and lose sight of it.

The field list is built from the schema tables, so an element offers exactly
the attributes its IFC class declares (inherited ones included, grouped by
the entity that declares them) plus every property set that applies to that
class. Nothing here is a hand-written list of fields to fall out of date.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from core.i18n import current_language
from core.group import Group
from views.fold_section import FoldSection, narrow, wrapping_form

from . import schema as schema_mod
from . import store

# English is the source language; anything missing falls through to it.
_TEXTS = {
    "es": {
        "IFC fields": "Campos IFC",
        "Nothing selected": "Nada seleccionado",
        "Select a tagged group or tagged faces to edit its IFC data.":
            "Selecciona un grupo o caras etiquetadas para editar sus datos "
            "IFC.",
        "This geometry is not an IFC object yet.":
            "Esta geometría todavía no es un objeto IFC.",
        "Tag it in the BIM panel first (or with Tag as you draw), then edit "
        "every field here.":
            "Etiquétala primero en el panel BIM (o con «Etiquetar al "
            "dibujar») y luego edita aquí todos los campos.",
        "Schema": "Esquema",
        "Class": "Clase",
        "Filter classes…": "Filtrar clases…",
        "All IFC entities": "Todas las entidades IFC",
        "Name": "Nombre",
        "Attributes": "Atributos",
        "Properties": "Propiedades",
        "Quantities": "Mediciones",
        "read-only, measured from the geometry":
            "sólo lectura, medido de la geometría",
        "(unset)": "(sin valor)",
        "not set": "sin valor",
        "Add property set…": "Añadir conjunto de propiedades…",
        "New property set": "Nuevo conjunto de propiedades",
        "Name of the property set:": "Nombre del conjunto de propiedades:",
        "Add property": "Añadir propiedad",
        "Property": "Propiedad",
        "Type": "Tipo",
        "Value": "Valor",
        "Remove": "Quitar",
        "A property set of your own. Its type is kept with it.":
            "Un conjunto de propiedades propio. Su tipo se guarda con él.",
        "IFC classification data from buildingSMART International.":
            "Datos de clasificación IFC de buildingSMART International.",
        "Choose an IFC class for this element.":
            "Elige una clase IFC para este elemento.",
        "The {cls} class does not exist in {schema}. Choose another class, "
        "or switch the schema.":
            "La clase {cls} no existe en {schema}. Elige otra clase o cambia "
            "el esquema.",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


def _unset(value) -> bool:
    """Whether a stored value means "no value", as IFC's ``$`` does."""
    return value is None or (isinstance(value, str) and not value.strip())


class _ValueEditor(QWidget):
    """One value, with an editor chosen from the IFC type.

    A boolean is not a tick box: in IFC an unset flag and a false one are
    different, and ``IsExternal`` being unknown is not the same as it being
    false. So every editor has an explicit empty state, and leaving it empty
    stores nothing.
    """

    def __init__(self, kind: str, value, enum=(), parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._kind = kind
        self._box = None
        self._edit = None
        self._check = None

        if kind == "boolean":
            self._box = QComboBox()
            self._box.addItem(_t("(unset)"), None)
            self._box.addItem("True", True)
            self._box.addItem("False", False)
            self._box.setCurrentIndex(
                0 if _unset(value) else (1 if value else 2))
            lay.addWidget(self._box)
        elif kind == "enum" and enum:
            self._box = QComboBox()
            self._box.addItem(_t("(unset)"), None)
            for name in enum:
                self._box.addItem(name, name)
            index = self._box.findData(value) if not _unset(value) else 0
            self._box.setCurrentIndex(max(index, 0))
            lay.addWidget(self._box)
        else:
            self._edit = QLineEdit()
            self._edit.setPlaceholderText(_t("not set"))
            if not _unset(value):
                self._edit.setText(str(value))
            lay.addWidget(self._edit)
        narrow(*[w for w in (self._box, self._edit) if w is not None])

    def value(self):
        """What to store: a bool, a number, a string, or None for unset."""
        if self._box is not None:
            return self._box.currentData()
        if self._edit is None:
            return None
        text = self._edit.text().strip()
        if not text:
            return None
        if self._kind in ("integer", "real", "number"):
            try:
                return int(text) if self._kind == "integer" else float(text)
            except ValueError:
                return text                 # keep what was typed; do not lie
        return text

    def changed(self, slot) -> None:
        """Call ``slot`` when the user commits a change."""
        if self._box is not None:
            self._box.currentIndexChanged.connect(lambda _i: slot())
        if self._edit is not None:
            self._edit.editingFinished.connect(slot)


class _AddPropertyDialog(QDialog):
    """Name, IFC type and value of a property the schema does not define."""

    def __init__(self, table, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_t("Add property"))
        self._types = sorted(table.types)
        form = QFormLayout(self)

        self._name = QLineEdit()
        form.addRow(_t("Name") + ":", self._name)

        self._type = QComboBox()
        self._type.setEditable(True)
        self._type.addItems(self._types)
        self._type.setCurrentText("IfcLabel")
        narrow(self._type)
        form.addRow(_t("Type") + ":", self._type)

        self._value = QLineEdit()
        form.addRow(_t("Value") + ":", self._value)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_tuple(self):
        return (self._name.text().strip(), self._type.currentText().strip(),
                self._value.text())


class IfcEditorPanel(QWidget):
    """The side-tray tab. Follows the selection; edits are one undo step."""

    def __init__(self, app) -> None:
        super().__init__()
        self._app = app
        #: Our own dock, attached by ``setup`` — see :meth:`_keep_in_front`.
        self._dock = None
        #: The JSON of what is on screen. Rebuild only when it changes: our own
        #: edits notify synchronously, and a rebuild mid-typing would steal the
        #: focus out of the field being typed into.
        self._signature: str | None = None
        self._key: str | None = None
        #: Set while we are writing, so the notification our own write causes
        #: does not rebuild the form under the user's fingers.
        self._writing = False
        #: Values still to be committed, gathered from the live editors.
        self._field_getters: dict = {}
        self._pset_getters: dict = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)

        self._status = QLabel(_t("Nothing selected"))
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # Everything below the status line only exists when an element is
        # selected, so there is nothing to grey out.
        self._top = QWidget()
        top = QVBoxLayout(self._top)
        top.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Schema") + ":"))
        self._schema_box = QComboBox()
        self._schema_box.addItems(list(schema_mod.SCHEMAS))
        narrow(self._schema_box)
        row.addWidget(self._schema_box)
        top.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Class") + ":"))
        self._all_entities = QCheckBox(_t("All IFC entities"))
        self._all_check = self._all_entities
        row.addWidget(self._all_entities)
        row.addStretch(1)
        top.addLayout(row)

        self._class_filter = QLineEdit()
        self._class_filter.setPlaceholderText(_t("Filter classes…"))
        top.addWidget(self._class_filter)

        self._class_box = QComboBox()
        self._class_box.setMaxVisibleItems(24)
        narrow(self._class_box)
        top.addWidget(self._class_box)

        row = QHBoxLayout()
        row.addWidget(QLabel(_t("Name") + ":"))
        self._name_edit = QLineEdit()
        row.addWidget(self._name_edit, 1)
        top.addLayout(row)
        outer.addWidget(self._top)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._host)
        outer.addWidget(self._scroll, 1)

        self._attribution = QLabel()
        self._attribution.setWordWrap(True)
        self._attribution.setStyleSheet("color: palette(mid); font-size: 10px;")
        outer.addWidget(self._attribution)

        self._schema_box.currentIndexChanged.connect(self._on_schema)
        self._all_entities.toggled.connect(self._fill_classes)
        self._class_filter.textChanged.connect(self._fill_classes)
        # currentIndexChanged, not activated: activated is overloaded (int and
        # str) and its resolution depends on the slot's arity. Every
        # programmatic change to this box goes through blockSignals, so only the
        # user's own choice arrives here.
        self._class_box.currentIndexChanged.connect(self._on_class)
        self._name_edit.editingFinished.connect(self._on_name)

        app.on_document_changed(self.refresh)
        self.refresh()

    # ---- what is selected ---------------------------------------------------
    def _table(self, schema: str):
        try:
            return schema_mod.load(schema)
        except Exception:                          # noqa: BLE001 — never break
            return None

    def _pick(self, scene):
        """The IFC object the panel is about: a tagged group if one is
        selected, else the first tagged faces. None when the selection holds
        no IFC object."""
        for entity in scene.selection:
            if isinstance(entity, Group) and store.object_key(entity):
                return entity
        for entity in scene.selection:
            if store.object_key(entity):
                return entity
        return None

    def _record(self) -> dict | None:
        scene = self._app.scene
        entity = self._pick(scene)
        return store.record(scene, entity) if entity is not None else None

    def attach_dock(self, dock) -> None:
        """Remember the tab this panel lives in, so an edit can come back to
        the front (see :meth:`_keep_in_front`)."""
        self._dock = dock

    def _keep_in_front(self) -> None:
        """Bring our own tab back to the front after our own write.

        Editing here changes the document, and that notifies the whole window:
        the other trays refresh too, and in a tabbed tray that can leave
        another panel's tab in front — which is the one thing an editing panel
        must not do, since the next thing the user does is edit the next field.

        Only when our own tab is still open: a panel the user closed from
        Window ▸ Panels stays closed.
        """
        dock = self._dock
        if dock is None or not dock.isVisible():
            return
        self._app.show_panel(dock)

    # ---- the refresh loop ---------------------------------------------------
    def refresh(self) -> None:
        if self._writing:
            return
        try:
            record = self._record()
        except Exception:                          # noqa: BLE001
            return
        # The signature has to tell apart the states that are not a record:
        # "nothing is selected" and "what is selected is not an IFC object" show
        # different things, and both are a missing record.
        if record is None:
            signature = ("untagged" if self._app.scene.selection else "empty")
        else:
            signature = json.dumps(record, sort_keys=True)
        if signature == self._signature:
            return
        self._signature = signature
        try:
            self._rebuild(record)
        except Exception:                          # noqa: BLE001 — never break
            self._status.setText(
                "ifc_editor: could not build the form for this element "
                "(see the log)")

    def _rebuild(self, record: dict | None) -> None:
        self._clear_host()
        self._field_getters = {}
        self._pset_getters = {}

        if record is None:
            self._key = None
            self._top.setVisible(False)
            self._scroll.setVisible(False)
            self._attribution.setVisible(False)
            selected = bool(self._app.scene.selection)
            if selected:
                self._status.setText(
                    _t("This geometry is not an IFC object yet.") + " "
                    + _t("Tag it in the BIM panel first (or with Tag as you "
                         "draw), then edit every field here."))
            else:
                self._status.setText(_t("Nothing selected") + " "
                                     + _t("Select a tagged group or tagged "
                                          "faces to edit its IFC data."))
            return

        self._status.setText(f"{record['class']}  —  "
                             f"{record['name'] or _t('not set')}")
        self._top.setVisible(True)
        self._scroll.setVisible(True)
        self._attribution.setVisible(True)
        self._key = record["key"]

        table = self._table(record["schema"])
        if table is None:
            return
        self._attribution.setText(_t("IFC classification data from "
                                     "buildingSMART International."))

        self._fill_top(table, record)

        # An element whose class this schema does not know — the other schema's
        # class, or one never set — has no field list to show. Offer the picker
        # and say so, rather than a blank form.
        if not record["class"]:
            self._status.setText(_t("Choose an IFC class for this element."))
            self._host_layout.addStretch(1)
            return
        if not table.has_entity(record["class"]):
            self._status.setText(
                _t("The {cls} class does not exist in {schema}. Choose "
                   "another class, or switch the schema.")
                .format(cls=record["class"], schema=record["schema"]))
            self._host_layout.addStretch(1)
            return

        # Attributes: the class's own fields, grouped by where they come from.
        section = FoldSection(_t("Attributes"),
                               "ifc_editor/section/attributes", self)
        self._host_layout.addWidget(section)
        self._fill_attributes(table, record, section)

        # Property sets that apply to this class, plus the user's own.
        self._fill_psets(table, record)

        # Quantities: measured, never typed.
        self._fill_quantities(record)

        self._host_layout.addStretch(1)

    def _clear_host(self) -> None:
        """Take the old form out of the layout and hand it to the event loop
        to delete — the usual Qt way.

        Everything added to the host is a widget, never a loose layout: a
        layout without a parent widget leaves its own children parentless, and
        they would linger as stray top-level windows. Reparenting to None here
        would do the same, which is why the widget is simply deleted.
        """
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                inner = item.layout()
                if inner is not None:
                    for i in range(inner.count()):
                        child = inner.takeAt(0).widget()
                        if child is not None:
                            child.deleteLater()

    # ---- class, name, schema ------------------------------------------------
    def _fill_top(self, table, record: dict) -> None:
        self._schema_box.blockSignals(True)
        index = self._schema_box.findText(record["schema"])
        self._schema_box.setCurrentIndex(max(index, 0))
        self._schema_box.blockSignals(False)

        self._all_entities.blockSignals(True)
        self._all_entities.setChecked(
            bool(record["class"]) and record["class"] not in table.product_names())
        self._all_entities.blockSignals(False)

        self._class_filter.blockSignals(True)
        self._class_filter.setText("")
        self._class_filter.blockSignals(False)
        self._fill_classes(keep=record["class"])

        self._name_edit.blockSignals(True)
        self._name_edit.setText(record["name"])
        self._name_edit.blockSignals(False)

    def _fill_classes(self, *_, keep: str | None = None) -> None:
        """Fill the class picker, filtered by what has been typed.

        Only what is in the box can be picked, so the current class has to stay
        in it even when the filter would drop it — otherwise clearing the
        filter would silently change the class.
        """
        record = self._record()
        if keep is None:
            keep = (record or {}).get("class") or self._class_box.currentText()
        all_entities = self._all_entities.isChecked()
        try:
            table = schema_mod.load((record or {}).get("schema", "IFC4"))
        except Exception:                          # noqa: BLE001
            return
        names = table.class_names() if all_entities else table.product_names()
        text = self._class_filter.text().strip().lower()
        if text:
            names = [n for n in names if text in n.lower()]
        if keep and keep not in names:
            names = [keep] + names

        self._class_box.blockSignals(True)
        self._class_box.clear()
        self._class_box.addItems(names)
        if keep:
            index = self._class_box.findText(keep)
            if index >= 0:
                self._class_box.setCurrentIndex(index)
        self._class_box.blockSignals(False)

    def _on_schema(self, _index: int) -> None:
        record = self._record()
        if record is None:
            return
        chosen = self._schema_box.currentText()
        self._commit(schema=chosen)

    def _on_class(self, _index: int) -> None:
        record = self._record()
        if record is None:
            return
        chosen = self._class_box.currentText()
        if not chosen or chosen == record["class"]:
            return
        self._commit(ifc_class=chosen)

    def _on_name(self) -> None:
        record = self._record()
        if record is None:
            return
        name = self._name_edit.text().strip()
        if name == record["name"]:
            return
        self._commit(name=name)

    # ---- attributes --------------------------------------------------------
    def _fill_attributes(self, table, record: dict, section: FoldSection) -> None:
        form = wrapping_form(section.body)

        last_origin = None
        for attribute in table.attributes(record["class"]):
            name = attribute["name"]
            origin = attribute.get("inherited_from")
            if origin and origin != last_origin:
                caption = QLabel(f"— {origin} —")
                caption.setStyleSheet("color: palette(mid); font-size: 10px;")
                form.addRow(caption)
                last_origin = origin

            kind = table.resolve_kind(attribute["type"])
            enum = attribute.get("enum") or table.enum_values(attribute["type"])
            value = record["fields"].get(name)

            if name in schema_mod.DERIVED_ATTRIBUTES:
                # Placement and representation are the geometry's, not the
                # user's: shown, so the record is complete, but not typed over.
                label = QLabel(str(value) if not _unset(value) else "—")
                label.setToolTip(attribute["type"] + " — derived from the "
                                 "geometry")
                label.setStyleSheet("color: palette(mid);")
                form.addRow(name + ":", label)
                continue

            editor = _ValueEditor(kind, value, enum)
            tooltip = attribute["type"]
            if attribute.get("optional"):
                tooltip += " (optional)"
            editor.setToolTip(tooltip)
            editor.changed(self._on_attributes)
            self._field_getters[name] = editor.value
            form.addRow(name + ":", editor)

    def _on_attributes(self) -> None:
        fields = {}
        for name, get in list(self._field_getters.items()):
            value = get()
            if not _unset(value):
                fields[name] = value
        self._commit(fields=fields)

    # ---- property sets -----------------------------------------------------
    def _fill_psets(self, table, record: dict) -> None:
        applicable = table.psets_for(record["class"],
                                     record["fields"].get("PredefinedType"))
        known = {name for name, _entry in applicable}
        for name in record["custom"]:
            if name not in known:
                applicable.append((name, {"kind": "pset", "properties": []}))

        for name, entry in applicable:
            title = name
            section = FoldSection(title, f"ifc_editor/section/{name}", self,
                                  default_open=bool(record["psets"].get(name)))
            self._host_layout.addWidget(section)
            self._fill_one_pset(table, record, name, entry, section)

        # In a holder widget, not a bare layout: everything in the host has to
        # be a widget, or clearing the panel would leave the button parentless
        # and it would linger as a stray top-level window.
        holder = QWidget()
        row = QHBoxLayout(holder)
        add = QPushButton(_t("Add property set…"))
        add.clicked.connect(self._on_add_pset)
        row.addWidget(add)
        row.addStretch(1)
        self._host_layout.addWidget(holder)

    def _fill_one_pset(self, table, record: dict, name: str, entry: dict,
                       section: FoldSection) -> None:
        form = wrapping_form(section.body)

        values = dict(record["psets"].get(name) or {})
        declared = {p["name"]: p for p in entry.get("properties", [])}
        custom_types = dict((record["pset_types"].get(name) or {}))

        getters: dict = {}
        for prop_name in list(declared) + [p for p in values
                                           if p not in declared]:
            spec = declared.get(prop_name, {})
            value_type = spec.get("value_type") or custom_types.get(prop_name) \
                or "IfcLabel"
            enum = spec.get("enum") or table.enum_values(value_type)
            kind = table.resolve_kind(value_type)
            editor = _ValueEditor(kind, values.get(prop_name), enum)
            tooltip = value_type
            if spec.get("property_type"):
                tooltip += f" — {spec['property_type']}"
            if spec.get("description"):
                tooltip = f"{spec['description']}\n\n{tooltip}"
            editor.setToolTip(tooltip)
            editor.changed(lambda n=name: self._on_psets(n))
            getters[prop_name] = editor.value
            form.addRow(prop_name + ":", editor)

        self._pset_getters[name] = getters

        if name in record["custom"]:
            note = QLabel(_t("A property set of your own. Its type is kept "
                             "with it."))
            note.setWordWrap(True)
            note.setStyleSheet("color: palette(mid); font-size: 10px;")
            form.addRow(note)
            row = QHBoxLayout()
            add = QPushButton(_t("Add property"))
            add.clicked.connect(lambda _c=False, n=name: self._on_add_property(n))
            row.addWidget(add)
            drop = QPushButton(_t("Remove"))
            drop.clicked.connect(lambda _c=False, n=name: self._on_drop_pset(n))
            row.addWidget(drop)
            row.addStretch(1)
            form.addRow(row)
            narrow(add, drop)

    def _on_psets(self, pset_name: str) -> None:
        record = self._record()
        if record is None:
            return
        getters = self._pset_getters.get(pset_name)
        if getters is None:
            return
        values = {}
        for prop_name, get in list(getters.items()):
            value = get()
            if not _unset(value):
                values[prop_name] = value
        psets = dict(record["psets"])
        if values or pset_name in record["custom"]:
            psets[pset_name] = values
        else:
            psets.pop(pset_name, None)
        self._commit(psets=psets)

    def _on_add_pset(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        # Through a single-shot so the dialog opens after the button's own
        # event has unwound — the same reason a context menu does.
        def ask():
            name, ok = QInputDialog.getText(self, _t("New property set"),
                                            _t("Name of the property set:"))
            name = (name or "").strip()
            if not ok or not name:
                return
            record = self._record()
            if record is None:
                return
            custom = list(record["custom"])
            if name not in custom:
                custom.append(name)
            self._commit(custom=custom)
        QTimer.singleShot(0, ask)

    def _on_add_property(self, pset_name: str) -> None:
        def ask():
            record = self._record()
            if record is None:
                return
            table = self._table(record["schema"])
            if table is None:
                return
            dialog = _AddPropertyDialog(table, self.window())
            if dialog.exec() != QDialog.Accepted:
                return
            prop_name, prop_type, text = dialog.result_tuple()
            if not prop_name:
                return
            values = dict(record["psets"].get(pset_name) or {})
            values[prop_name] = text
            types = dict(record["pset_types"])
            types[pset_name] = dict(types.get(pset_name) or {},
                                    **{prop_name: prop_type})
            self._commit(psets=dict(record["psets"], **{pset_name: values}),
                         pset_types=types)
        QTimer.singleShot(0, ask)

    def _on_drop_pset(self, pset_name: str) -> None:
        record = self._record()
        if record is None:
            return
        custom = [n for n in record["custom"] if n != pset_name]
        psets = dict(record["psets"])
        psets.pop(pset_name, None)
        types = dict(record["pset_types"])
        types.pop(pset_name, None)
        self._commit(custom=custom, psets=psets, pset_types=types)

    # ---- quantities --------------------------------------------------------
    def _fill_quantities(self, record: dict) -> None:
        try:
            from core.bim import class_quantities
            faces, groups = store.resolve(self._app.scene, record["key"])
            if groups and not faces:
                faces = list(groups[0].mesh.faces)
            _qset, entries, (metrado, unit) = class_quantities(
                record["class"], faces)
        except Exception:                          # noqa: BLE001
            return
        if not entries and metrado is None:
            return
        section = FoldSection(_t("Quantities"),
                              "ifc_editor/section/quantities", self,
                              default_open=False)
        self._host_layout.addWidget(section)
        form = wrapping_form(section.body)
        caption = QLabel(_t("read-only, measured from the geometry"))
        caption.setStyleSheet("color: palette(mid); font-size: 10px;")
        form.addRow(caption)
        for kind, name, value in entries:
            form.addRow(f"{name}:", QLabel(f"{value:.4f} {kind}"))
        if metrado is not None:
            form.addRow(f"{_t('Quantities')}:", QLabel(f"{metrado:.4f} {unit}"))

    # ---- writing -----------------------------------------------------------
    def _commit(self, **changes) -> None:
        """Write through the store, as one undo step, without rebuilding the
        form the user is working in."""
        record = self._record()
        if record is None:
            return
        self._writing = True
        try:
            store.edit(self._app.viewport, record["key"], **changes)
        finally:
            self._writing = False
        try:
            fresh = self._record()
        except Exception:                          # noqa: BLE001
            fresh = None
        self._signature = (json.dumps(fresh, sort_keys=True)
                           if fresh is not None else None)
        # A class change rebuilds the field list; everything else keeps the
        # widgets the user is in.
        if "ifc_class" in changes or "schema" in changes:
            self._signature = None
            self.refresh()
        # Last, so nothing the rebuild did can leave another tab in front.
        self._keep_in_front()
