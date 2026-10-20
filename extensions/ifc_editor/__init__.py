# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""IFC fields — edit every attribute and property set of a tagged element.

Tested with IngeTrazo 0.5.8 (extension API 2).

IngeTrazo tags what you draw with a class and a name and writes only those
into its IFC export: ``Description``, ``ObjectType``, ``PredefinedType`` and
every ``Pset_*`` come out as ``$``. This extension is the missing half —
select a IFC object and edit all of it:

* every attribute the element's IFC class declares, inherited ones included
  and grouped by the entity that declares them;
* every property set that applies to that class, with its real value types —
  enums as lists, booleans that can be left *unset* (which in IFC is not the
  same as false);
* property sets of your own, for what buildingSMART does not define;
* any of the 776 IFC4 (or 653 IFC2X3) entities as the class, not just the 16
  the core curates.

The class and the name are written back into IngeTrazo's own BIM tag, so the
BIM panel, the take-off and the core's export never disagree with what is
shown here. Everything else is this extension's, saved in the document.

Field lists come from schema tables generated offline from buildingSMART's own
EXPRESS schemas and property-set definitions — the extension carries no
dependency and needs no installer. IFC is a trademark of, and these
definitions are copyright, buildingSMART International Limited; the tables
record the attribution, and ``dev/schema/`` in the project that built them
documents the provenance.

Install: ``./dev/install.sh``, then restart IngeTrazo. The panel is also in
Window ▸ Panels and the Extensions menu.
"""
from __future__ import annotations

import logging

from core.i18n import current_language

log = logging.getLogger("ingetrazo.plugins")

_TEXTS = {
    "es": {
        "IFC fields": "Campos IFC",
        "IFC": "IFC",
        "Edit every attribute and property set of the selected IFC object.":
            "Edita todos los atributos y conjuntos de propiedades del objeto "
            "IFC seleccionado.",
        "Export IFC4 (full)…": "Exportar IFC4 (completo)…",
        "Export IFC2X3 (full)…": "Exportar IFC2X3 (completo)…",
        "{schema} (*.ifc);;All files (*)": "{schema} (*.ifc);;Todos los archivos (*)",
        "Wrote {n} element(s) to {path}": "{n} elemento(s) escritos en {path}",
        "Not written:": "No escritos:",
        "IFC export": "Exportación IFC",
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


def export(app, schema: str = "IFC4") -> None:
    """Write the document as IFC, with the fields this extension holds.

    The schema is a choice because it matters to the reader: IFC2X3 keeps a
    predefined type on a *type object*, IFC4 on the element, and a file has to
    say one thing or the other.
    """
    from views.filedialogs import file_dialogs

    from . import writer

    path, _filter = file_dialogs.getSaveFileName(
        app.window, _t("Export IFC (full)"),
        f"model-{schema.lower()}.ifc",
        _t("{schema} (*.ifc);;All files (*)", schema=schema))
    if not path:
        return
    dropped: list = []
    try:
        count = writer.save(app.scene, path, schema=schema, dropped=dropped)
    except ValueError as exc:
        app.viewport.flash_status(str(exc), 6000)
        return
    except Exception as exc:                           # noqa: BLE001
        log.exception("ifc_editor: the export failed")
        app.viewport.flash_status(f"IFC: {exc}", 8000)
        return
    message = _t("Wrote {n} element(s) to {path}", n=count, path=path)
    if dropped:
        # A field that could not be written is said out loud: editing it and
        # being told nothing is how a panel stops being trusted.
        _say(app, message + "\n\n" + _t("Not written:") + "\n"
             + "\n".join(f"· {note}" for note in dropped[:15])
             + (f"\n… {len(dropped) - 15} more" if len(dropped) > 15 else ""))
        return
    app.viewport.flash_status(message, 5000)


def _say(app, text: str) -> None:
    from PySide6.QtWidgets import QMessageBox

    message = QMessageBox(app.window)
    message.setIcon(QMessageBox.INFORMATION)
    message.setWindowTitle(_t("IFC export"))
    message.setText(text)
    message.exec()


def setup(app) -> None:
    """Called once, when the main window is built."""
    from . import schema as schema_mod
    from .panel import IfcEditorPanel

    # Say so in the log rather than failing later, inside a repaint.
    for schema in schema_mod.SCHEMAS:
        if not schema_mod.available(schema):
            log.warning("ifc_editor: the %s schema table is missing from the "
                        "extension's data/ folder; that schema cannot be "
                        "edited", schema)

    panel = IfcEditorPanel(app)
    dock = app.add_panel(_t("IFC"), panel)
    panel.attach_dock(dock)

    # A panel with a menu entry can be brought back after being hidden in
    # Window ▸ Panels; the panel also carries the class picker, so this is how
    # people will find it.
    #
    # Ctrl+Shift+F, and NOT Ctrl+Shift+I: add_menu_action only refuses a
    # shortcut another EXTENSION took, so the app's own are not checked and a
    # clash silently makes both ambiguous. In 0.5.8 Ctrl+Shift+I is already
    # Edit ▸ Invert Selection; taken letters are A C G H I N P V Z.
    app.add_menu_action(
        _t("IFC fields"), lambda: app.show_panel(dock), shortcut="Ctrl+Shift+F",
        tip=_t("Edit every attribute and property set of the selected IFC "
               "object."))

    # The other half: a file that carries what you edited. The core's own
    # Export IFC writes a fixed, narrow set, so this is not a duplicate of it.
    app.add_menu_action(
        _t("Export IFC4 (full)…"), lambda: export(app, "IFC4"),
        tip=_t("Write an .ifc with every attribute and property set you "
               "edited, and the openings in our walls."))
    # IFC2X3 as well: the user's own project files are IFC2X3, and a predefined
    # type written on the wrong entity is a field that silently does not travel.
    app.add_menu_action(
        _t("Export IFC2X3 (full)…"), lambda: export(app, "IFC2X3"),
        tip=_t("Write the same document in IFC2X3, with a predefined type as an "
               "IfcWallType where that schema keeps it."))
