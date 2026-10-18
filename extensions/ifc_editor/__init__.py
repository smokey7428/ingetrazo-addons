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
    },
}


def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text


def export(app) -> None:
    """Write the document as IFC, with the fields this extension holds."""
    from views.filedialogs import file_dialogs

    from . import writer

    path, _filter = file_dialogs.getSaveFileName(
        app.window, _t("Export IFC (full)"), "model.ifc",
        _t("IFC4 (*.ifc);;All files (*)"))
    if not path:
        return
    try:
        count = writer.save(app.scene, path, schema="IFC4")
    except ValueError as exc:
        app.viewport.flash_status(str(exc), 6000)
        return
    except Exception as exc:                           # noqa: BLE001
        log.exception("ifc_editor: the export failed")
        app.viewport.flash_status(f"IFC: {exc}", 8000)
        return
    app.viewport.flash_status(
        _t("Wrote {n} element(s) to {path}", n=count, path=path), 5000)


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
        _t("Export IFC (full)…"), lambda: export(app),
        tip=_t("Write an .ifc with every attribute and property set you "
               "edited, and the openings in our walls."))
