#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Drive the ifc_editor panel's logic headlessly, against stubbed Qt.

This runs the real panel code — building the form for a tagged element, filling
it from the schema tables, committing an edit, undoing it — with
``dev/tests/qt_stubs.py`` standing in for PySide6. It catches the things that
break a panel before it ever draws: a name that does not exist, a form built
from the wrong field list, an edit that writes the wrong storage or takes two
undo steps.

It cannot tell you whether anything looks right. That is a restart of
IngeTrazo with the extension installed.

Usage:  python3 dev/tests/test_ifc_editor_panel.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import qt_stubs                                                    # noqa: E402

EXT = HERE.parent.parent / "extensions" / "ifc_editor"

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


# ---- the core, stubbed ------------------------------------------------------
def install_core_stubs() -> None:
    core = __import__("types").ModuleType("core")
    core.__path__ = []
    sys.modules["core"] = core

    i18n = __import__("types").ModuleType("core.i18n")
    i18n.current_language = lambda: "en"
    sys.modules["core.i18n"] = i18n

    mesh = __import__("types").ModuleType("core.mesh")

    class Face:
        def __init__(self, ifc=None):
            self.attrs = {} if ifc is None else {"ifc": dict(ifc)}

    class Edge:
        pass

    mesh.Face, mesh.Edge = Face, Edge
    sys.modules["core.mesh"] = mesh

    group = __import__("types").ModuleType("core.group")

    class Group:
        def __init__(self, name="Group", uid="uid0001", ifc=None):
            self.name, self.uid, self.ifc = name, uid, ifc
            self.mesh = __import__("types").SimpleNamespace(faces=[])

    group.Group = Group
    sys.modules["core.group"] = group

    history = __import__("types").ModuleType("core.history")

    class Command(__import__("abc").ABC):
        @__import__("abc").abstractmethod
        def do(self, scene):
            """apply"""

        @__import__("abc").abstractmethod
        def undo(self, scene):
            """reverse"""

    history.Command = Command
    sys.modules["core.history"] = history

    bim = __import__("types").ModuleType("core.bim")

    def collect_objects(scene):
        out = []
        by_id: dict = {}
        for face in scene.loose_mesh.faces:
            tag = face.attrs.get("ifc")
            if tag:
                by_id.setdefault(tag.get("id"), []).append(face)
        for obj_id, faces in by_id.items():
            out.append({"faces": faces})
        for g in scene.groups:
            if getattr(g, "ifc", None):
                out.append({"group": g})
        return out

    def class_quantities(ifc_class, faces):
        entries = [("length", "Height", 2.7), ("area", "GrossSideArea", 8.1)]
        return "Qto_WallBaseQuantities", entries, (7.2, "m2")

    bim.collect_objects = collect_objects
    bim.class_quantities = class_quantities
    bim.next_object_id = lambda scene: 99
    sys.modules["core.bim"] = bim


class Scene:
    def __init__(self):
        self.plugin_data: dict = {}
        self.version = 0
        self.groups: list = []
        self.loose_mesh = __import__("types").SimpleNamespace(faces=[])
        self.selection: list = []


class History:
    def __init__(self, scene):
        self._scene = scene
        self.undo_stack: list = []

    def execute(self, command) -> None:
        command.do(self._scene)
        self.undo_stack.append(command)

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.undo_stack.pop().undo(self._scene)
        return True


class Viewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.updates = 0
        self.status: list = []

    def flash_status(self, text: str, _ms: int = 0) -> None:
        self.status.append(text)

    def update(self) -> None:
        self.updates += 1

    def notify_scene_changed(self) -> None:
        self.updates += 1


class FakeDock:
    """A dock widget: visible until hidden, as a tabbed dock is."""

    def __init__(self, title, widget, name=None):
        self.title, self.widget, self.name = title, widget, name
        self._visible = True

    def isVisible(self) -> bool:
        return self._visible

    def objectName(self) -> str:
        return "extension_ifc_editor"


class FakeApp:
    """What :meth:`ExtensionApp` offers, recorded."""

    def __init__(self, scene, viewport):
        self.scene, self.viewport = scene, viewport
        self.key = "ifc_editor"
        self.window = None          # the parent a dialog would hang off
        self.panels: dict = {}
        self.menu_actions: list = []
        self.shown = None
        self._on_changed: list = []

    def on_document_changed(self, fn) -> None:
        self._on_changed.append(fn)

    def add_panel(self, title, widget, name=None, **kw):
        dock = FakeDock(title, widget, name)
        self.panels[title] = dock
        return dock

    def show_panel(self, dock) -> None:
        self.shown = dock

    def add_menu_action(self, text, fn, shortcut=None, tip=None):
        self.menu_actions.append((text, fn, shortcut, tip))
        return text

    def changed(self) -> None:
        for fn in self._on_changed:
            fn()


def load_package():
    """Import the extension the way IngeTrazo's loader does."""
    spec = importlib.util.spec_from_file_location(
        "ingetrazo_plugin_ifc_editor", EXT / "__init__.py",
        submodule_search_locations=[str(EXT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def label_texts(widget) -> list[str]:
    out = []
    for child in _descend(widget):
        text = getattr(child, "text", None)
        if callable(text) and type(child).__name__ == "QLabel":
            out.append(text())
    return out


def _descend(widget, seen=None) -> list:
    """Every widget under ``widget``, through layouts and fold bodies alike."""
    seen = set() if seen is None else seen
    if id(widget) in seen:
        return []
    seen.add(id(widget))
    found: list = []
    for name in ("_host_layout", "layout"):
        layout = getattr(widget, name, None)
        if not hasattr(layout, "widgets"):
            continue
        for child in layout.widgets():
            found.append(child)
            found.extend(_descend(child, seen))
    body = getattr(widget, "body", None)
    if body is not None and hasattr(body, "layout"):
        found.extend(_descend(body, seen))
    if type(widget).__name__ == "QScrollArea":
        inner = widget.widget()
        if inner is not None:
            found.append(inner)
            found.extend(_descend(inner, seen))
    return found


def find(widget, cls: str, want_text: str | None = None):
    """The first child of that Qt class (and text), or None."""
    for child in _descend(widget):
        if type(child).__name__ != cls:
            continue
        if want_text is None:
            return child
        if getattr(child, "_text", None) == want_text:
            return child
    return None


def main() -> int:
    qt_stubs.install()
    install_core_stubs()
    module = load_package()

    scene = Scene()
    viewport = Viewport(scene)
    app = FakeApp(scene, viewport)

    Group = sys.modules["core.group"].Group
    wall = Group(name="Wall A", uid="uid0001",
                 ifc={"class": "IfcWall", "name": "Wall A"})
    scene.groups.append(wall)

    # ---- setup(app) ----
    module.setup(app)
    store = sys.modules["ingetrazo_plugin_ifc_editor.store"]
    equal(list(app.panels), ["IFC"], "setup adds one panel, titled IFC")
    equal(len(app.menu_actions), 3,
          "and three Extensions-menu entries: the panel, and a full export in "
          "each schema — IFC2X3 is what the user's own project files are")
    text, _fn, shortcut, tip = app.menu_actions[0]
    # The app's own shortcuts are NOT checked by add_menu_action, so a clash
    # here makes both the app's action and ours ambiguous. Refresh this list
    # with:  grep -rhoE '"Ctrl\+Shift\+[A-Za-z]"' views/ core/ | sort -u
    taken_by_the_app = {"Ctrl+Shift+A", "Ctrl+Shift+C", "Ctrl+Shift+G",
                        "Ctrl+Shift+H", "Ctrl+Shift+I", "Ctrl+Shift+N",
                        "Ctrl+Shift+P", "Ctrl+Shift+V", "Ctrl+Shift+Z"}
    check(shortcut not in taken_by_the_app,
          f"the menu shortcut {shortcut!r} is already the app's own")
    check(bool(tip), "the menu entry carries a tip for the status bar and F3")
    panel = app.panels["IFC"].widget

    # ---- nothing selected ----
    panel.refresh()
    check("Nothing selected" in panel._status.text(),
          f"the status line with an empty selection: "
          f"{panel._status.text()!r}")

    # ---- an untagged group says what to do about it ----
    untagged = Group(name="Box", uid="other", ifc=None)
    scene.selection = [untagged]
    panel.refresh()
    check("not an IFC object yet" in panel._status.text(),
          f"untagged geometry should be explained: {panel._status.text()!r}")

    # ---- a tagged wall: the form is built from the schema ----
    scene.selection = [wall]
    panel.refresh()
    check("IfcWall" in panel._status.text(),
          f"the status names the class: {panel._status.text()!r}")

    # Every attribute of IfcWall should have an editor, derived ones aside.
    for name in ("Name", "Description", "ObjectType", "Tag", "GlobalId",
                 "PredefinedType"):
        check(name in panel._field_getters,
              f"the form should offer {name} for an IfcWall")
    check("ObjectPlacement" not in panel._field_getters,
          "a derived attribute must not be editable")
    check("Representation" not in panel._field_getters,
          "nor the representation")

    # PredefinedType is an enum, so it must be a list, not a text box.
    kinds = {name: _inner_kind(_editor_named(panel, name))
             for name in panel._field_getters}
    equal(kinds.get("PredefinedType"), "QComboBox",
          "an enumerated attribute should be a list, not a text box")
    equal(kinds.get("Name"), "QLineEdit", "and a label a text box")
    equal(kinds.get("Tag"), "QLineEdit", "and so should the tag")

    # The class picker reaches past the core's curated 16.
    box = panel._class_box
    check(box.count() > 120, f"the class picker offers {box.count()} classes")
    equal(box.currentText(), "IfcWall", "and shows the element's class")
    check("IfcCurtainWall" in [box.itemText(i) for i in range(box.count())],
          "IfcCurtainWall should be pickable")

    # Applicable property sets, with the standard's own value types.
    pset_names = list(panel._pset_getters)
    check("Pset_WallCommon" in pset_names,
          f"Pset_WallCommon should be offered: {pset_names[:4]}")
    if "Pset_WallCommon" in pset_names:
        is_external = panel._pset_getters["Pset_WallCommon"].get("IsExternal")
        check(is_external is not None,
              "and its IsExternal property should have an editor")
        if is_external is not None:
            equal(is_external(), None, "which starts unset, as IFC's $ does")

    check("Qto" in "".join(label_texts(panel))
          or any(n.startswith("Qto_") for n in panel._pset_getters),
          "the quantity set should be offered too")

    # ---- editing writes through, as one undo step ----
    before = json.dumps(scene.plugin_data, sort_keys=True)
    version = scene.version
    editor = _editor_named(panel, "Tag")
    check(editor is not None, "the Tag attribute should have an editor")
    # A plain field edit must NOT rebuild the form: rebuilding destroys the
    # widget the user is in, and Qt hands the focus to whatever comes next —
    # in a tabbed tray, another panel's widget, and with it that panel's tab.
    widgets_before = id(panel._field_getters)
    check(_type_into(editor, "W-01"), "the Tag editor is a text field")
    equal(id(panel._field_getters), widgets_before,
          "a plain edit keeps the form it is editing")
    equal(store.record(scene, wall)["fields"].get("Tag"), "W-01",
          "the typed Tag is stored")
    equal(scene.version, version + 1, "and it was one undo step")

    # The tab we live in has to stay in front. Editing notifies the whole
    # window — every tray refreshes — and in a tabbed tray another panel's tab
    # can end up in front of the field the user is about to fill in next.
    equal(app.shown, app.panels["IFC"], "an edit brings our own tab back")

    # But a panel the user closed from Window ▸ Panels stays closed.
    dock = app.panels["IFC"]
    dock._visible = False
    app.shown = None
    _type_into(_editor_named(panel, "Description"), "a load-bearing wall")
    equal(app.shown, None, "a closed panel is not resurrected by an edit")
    dock._visible = True

    # A second edit must not clobber the first.
    name_editor = panel._name_edit
    name_editor.setText("Wall A renamed")
    name_editor.editingFinished.emit()
    equal(wall.ifc["name"], "Wall A renamed",
          "the name goes into the core's own BIM tag")
    equal(store.record(scene, wall)["fields"].get("Tag"), "W-01",
          "and the earlier edit survives")

    # A property set value is stored where it belongs, not among the fields.
    _choose(panel, "Pset_WallCommon", "IsExternal", True)
    psets = store.record(scene, wall)["psets"]
    equal(psets.get("Pset_WallCommon", {}).get("IsExternal"), True,
          "the boolean went into its property set")
    check("IsExternal" not in store.record(scene, wall)["fields"],
          "and not into the attributes")

    # Unset is not false: clearing it again must remove the key, not store a
    # False that would be written into the file as an answer.
    _choose(panel, "Pset_WallCommon", "IsExternal", None)
    check("Pset_WallCommon" not in store.record(scene, wall)["psets"]
          or "IsExternal" not in store.record(scene, wall)["psets"]
          .get("Pset_WallCommon", {}),
          "clearing a property removes it rather than writing False")

    # ---- undo puts everything back ----
    while viewport.history.undo():
        pass
    equal(store.record(scene, wall)["fields"].get("Tag"), None,
          "undo removes the Tag")
    equal(wall.ifc["name"], "Wall A", "and restores the core tag's name")
    equal(json.dumps(scene.plugin_data, sort_keys=True), before,
          "the plugin data is back to what it was")

    # ---- changing the class rewrites the field list AND the core tag ----
    box = panel._class_box
    index = box.findText("IfcDoor")
    check(index >= 0, "IfcDoor should be pickable")
    if index >= 0:
        box.setCurrentIndex(index)
        box.currentIndexChanged.emit(index)
        equal(wall.ifc["class"], "IfcDoor",
              "the class reaches IngeTrazo's own BIM tag")
        check("OverallHeight" in panel._field_getters,
              "and the form follows: a door carries OverallHeight")
        check("OperationType" in panel._field_getters,
              "and OperationType, which a wall has not")
        door_psets = list(panel._pset_getters)
        check("Pset_DoorCommon" in door_psets,
              f"the door's own property sets appear: {door_psets[:4]}")
        check("Pset_WallCommon" not in door_psets,
              "and the wall's are gone")
        # Put it back for the rest of the test.
        index = box.findText("IfcWall")
        box.setCurrentIndex(index)
        box.currentIndexChanged.emit(index)
        equal(wall.ifc["class"], "IfcWall", "the class change is reversible")

    # ---- a boolean is not a tick box ----
    panel.refresh()
    combo = getattr(_getter_widget(panel, "Pset_WallCommon", "IsExternal"),
                    "_box", None)
    check(combo is not None and combo.count() == 3,
          "a boolean offers unset, True and False — three states, not two")

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    # ---- the export, through the menu, with a real file ----
    import tempfile
    from pathlib import Path as _Path

    from views.filedialogs import file_dialogs

    room = _Path(tempfile.mkdtemp(prefix="ingetrazo-ifc-"))
    target = room / "model-2x3.ifc"
    file_dialogs.next_path = str(target)
    try:
        entry = next((action for action in app.menu_actions
                      if action[0].startswith("Export IFC2X3")), None)
        check(entry is not None, "the menu offers an IFC2X3 export")
        entry[1]()
        check(target.is_file(), f"and it writes the file the dialog chose: "
                                f"{app.viewport.status[-1:] or 'no message'}")
        text = target.read_text(encoding="ascii") if target.is_file() else ""
        check(text.startswith("ISO-10303-21;"), "which is a STEP file")
        check("FILE_SCHEMA(('IFC2X3'));" in text, "declaring IFC2X3")
        check("IFCWALLSTANDARDCASE" in text,
              "with the wall as a standard case, as IFC2X3 wants it")
        check("IFCWALLTYPE" in text,
              "and the predefined type carried as a type object")
    finally:
        file_dialogs.next_path = None
        import shutil
        shutil.rmtree(room, ignore_errors=True)

    print(f"ifc_editor panel: ok ({checks} checks)")
    return 0


def _editors(panel, _kind):
    return dict(panel._field_getters)


def _inner_kind(editor):
    """Which kind of widget an editor actually put on screen."""
    if editor is None:
        return None
    if getattr(editor, "_box", None) is not None:
        return type(editor._box).__name__
    if getattr(editor, "_edit", None) is not None:
        return type(editor._edit).__name__
    return None


def _editor_named(panel, name: str):
    """The widget behind a field's getter, found by walking the form.

    Compared by equality, not identity: a bound method is a fresh object on
    every attribute access, so ``is`` would never match.
    """
    want = panel._field_getters.get(name)
    if want is None:
        return None
    return _editor_of(panel, want)


def _editor_of(root, want):
    for child in _descend(root):
        if getattr(child, "value", None) == want \
                and getattr(child, "_kind", None) is not None:
            return child
    return None


def _getter_widget(panel, pset_name: str, prop_name: str):
    """The editor widget for one property of one property set."""
    want = panel._pset_getters.get(pset_name, {}).get(prop_name)
    return None if want is None else _editor_of(panel, want)


def _type_into(editor, text: str) -> bool:
    """Type into an editor and commit it, as a user would."""
    inner = getattr(editor, "_edit", None)
    if inner is None:
        return False
    inner.setText(text)
    inner.editingFinished.emit()
    return True


def _choose(panel, pset_name: str, prop_name: str, value) -> bool:
    """Pick a value from an editor that is a list, as a user would."""
    editor = _getter_widget(panel, pset_name, prop_name)
    box = getattr(editor, "_box", None)
    if box is None:
        return False
    index = box.findData(value)
    if index < 0:
        return False
    box.setCurrentIndex(index)
    box.currentIndexChanged.emit(index)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
