#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Drive the whole doors extension headlessly: panel, tool, scenes.

Qt is stubbed (``dev/tests/qt_stubs.py``) and so is the core
(``app_stubs.py``), so this runs without IngeTrazo. It exercises the real code
paths — ``setup(app)`` registering the panel and the tool, the tool placing a
door from a click, the panel editing it, the menu actions — which is where a
typo in a widget name or a wrong argument lives.

What it cannot tell you: whether anything *looks* right, or whether a Qt enum
is used correctly. That needs a restart of IngeTrazo.

Usage:  python3 dev/tests/test_openings_panel.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app_stubs                                                    # noqa: E402
import qt_stubs                                                     # noqa: E402

EXT = HERE.parent.parent / "extensions" / "openings"

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


# ---- a stand-in for the application -----------------------------------------
class FakeDock:
    def __init__(self, title, widget, name=None):
        self.title, self.widget, self.name = title, widget, name
        self._visible = True

    def isVisible(self) -> bool:
        return self._visible

    def objectName(self) -> str:
        return "extension_openings"


class FakeActionGroup:
    def __init__(self):
        self.actions: list = []

    def addAction(self, action) -> None:
        self.actions.append(action)


class FakeAction:
    def __init__(self, text, parent=None):
        self._text = text
        self._parent = parent
        self.triggered = FakeSignal()

    def setCheckable(self, _on) -> None:
        pass

    def setToolTip(self, _tip) -> None:
        pass

    def setStatusTip(self, _tip) -> None:
        pass

    def text(self) -> str:
        return self._text


class FakeSignal:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class FakeWindow:
    def __init__(self):
        self._tools: dict = {}
        self._tool_actions: dict = {}
        self._tool_group = FakeActionGroup()
        self.activated: list = []

    def _activate_tool(self, key: str) -> None:
        self.activated.append(key)


class FakeViewport:
    def __init__(self, scene):
        self.scene = scene
        self.history = app_stubs.History(scene)
        self.camera = types.SimpleNamespace(
            target=app_stubs.QVector3D(), distance=12.0, yaw=0.0, pitch=0.0,
            perspective=True, set_view=self._set_view)
        self.active_tool = None
        self.messages: list = []
        self.picked_face = None
        self.picked_point = None
        #: What ``pick_face_any`` finds when ``pick_face`` finds nothing — a
        #: face that belongs to a group, which is the one case worth telling
        #: the user about.
        self.behind_face = None

    def _set_view(self, name: str) -> None:
        self.camera.yaw, self.camera.pitch = {"top": (0.0, 1.57),
                                              "front": (0.0, 0.0),
                                              "iso": (-0.7, 0.5)}.get(name, (0, 0))

    def update(self) -> None:
        pass

    def notify_scene_changed(self) -> None:
        pass

    def flash_status(self, text, msec=2500) -> None:
        self.messages.append(text)

    def pick_face(self, x, y):
        return self.picked_face

    def pick_face_any(self, x, y):
        if self.behind_face is None:
            return None, None
        return self.behind_face, "a group"

    def _world_under_cursor(self, x, y):
        return self.picked_point


class FakeApp:
    def __init__(self, scene, viewport, window):
        self.scene, self.viewport, self.window = scene, viewport, window
        self.key = "openings"
        self.panels: dict = {}
        self.menus: list = []
        self.context_menus: list = []
        self.outliner_kinds: list = []
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

    def add_menu(self, title):
        menu = types.SimpleNamespace(title=title, actions=[],
                                     addAction=lambda *a: menu.actions.append(a),
                                     addSeparator=lambda: None)
        self.menus.append(menu)
        return menu

    def add_menu_action(self, text, fn, shortcut=None, tip=None):
        self.menus.append(("action", text, fn))
        return text

    def add_context_menu(self, fn) -> None:
        self.context_menus.append(fn)

    def add_outliner_kind(self, fn) -> None:
        self.outliner_kinds.append(fn)


class FakeQtGui:
    """The two classes the extension builds actions and matrices with."""

    @staticmethod
    def install() -> None:
        import PySide6
        gui = types.ModuleType("PySide6.QtGui")
        gui.QVector3D = app_stubs.QVector3D
        gui.QVector4D = app_stubs.QVector4D
        gui.QMatrix4x4 = app_stubs.QMatrix4x4
        gui.QAction = FakeAction
        sys.modules["PySide6.QtGui"] = gui


def load(name: str):
    """One module per extension file, as in the app.

    Reloading a module here would give the panel and the test separate copies,
    and separate caches: the panel would keep showing the library it loaded
    before the test changed it, and the test would be checking the other one.
    """
    full = f"ingetrazo_plugin_openings.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, EXT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    setattr(sys.modules["ingetrazo_plugin_openings"], name, module)
    spec.loader.exec_module(module)
    return module


def install_package() -> None:
    package = types.ModuleType("ingetrazo_plugin_openings")
    package.__path__ = [str(EXT)]
    sys.modules["ingetrazo_plugin_openings"] = package


def install_tools_stub() -> None:
    """``tools.base.Tool`` — the base class a plugin tool subclasses. Only the
    class attributes and the hook names matter here."""
    tools = types.ModuleType("tools")
    tools.__path__ = []
    base = types.ModuleType("tools.base")

    class Tool:
        name = "Unnamed"
        description = None
        uses_snap = True
        box_select = False
        wireframe_color = None

        def on_activate(self, viewport) -> None:
            pass

        def on_deactivate(self, viewport) -> None:
            pass

        def on_click(self, ctx) -> None:
            pass

        def on_hover(self, ctx) -> None:
            pass

        def on_cancel(self, viewport) -> None:
            pass

    base.Tool = Tool
    tools.base = base
    sys.modules["tools"] = tools
    sys.modules["tools.base"] = base


def wall(scene) -> None:
    """A wall with two sides, on the Walls layer — one face of it is what the
    tool must pick."""
    scene.layers.append(app_stubs.Layer("Walls"))
    V = app_stubs.QVector3D
    c = [(0, 0, 0), (4, 0, 0), (4, 0.3, 0), (0, 0.3, 0),
         (0, 0, 2.7), (4, 0, 2.7), (4, 0.3, 2.7), (0, 0.3, 2.7)]
    for a, b, cc, d in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        face = scene.mesh.add_face([V(*c[a]), V(*c[b]), V(*c[cc]), V(*c[d])])
        face.attrs = {"layer": "Walls"}


def front_face(scene):
    for face in scene.mesh.faces:
        if abs(face.normal().normalized().y() + 1.0) < 1e-6:
            return face
    raise AssertionError("no front face")


def context(viewport, point, screen=(100.0, 100.0)):
    return types.SimpleNamespace(viewport=viewport, world=point,
                                 screen=types.SimpleNamespace(x=lambda: screen[0],
                                                              y=lambda: screen[1]),
                                 modifiers=None, snap=None)


def main() -> int:
    qt_stubs.install()
    app_stubs.install()
    FakeQtGui.install()
    install_package()
    install_tools_stub()

    params_mod = load("params")
    load("profiles")
    load("geometry")
    load("opening")
    object_mod = load("object")
    load("host")
    scenes_mod = load("scenes")
    tool_mod = load("tool")
    load("panel")
    extension = load("__init__")
    # Revealing a folder must not actually open one: a test run would leave
    # Finder windows behind. Recorded instead, and checked below.
    launched: list = []
    extension._launch = launched.append

    scene = app_stubs.Scene()
    wall(scene)
    viewport = FakeViewport(scene)
    window = FakeWindow()
    app = FakeApp(scene, viewport, window)

    # ---- setup(app) ----
    extension.setup(app)
    equal(list(app.panels), ["Openings", "Walls", "Take-off"],
          "setup adds the Openings, Walls and Take-off panels")
    panel = app.panels["Openings"].widget
    check(panel._dock is not None, "the panel knows its own tab")
    # Two chapters, not one: the openings are one half of this extension and
    # the walls the other, and a wall type file under "Doors & windows" made the
    # walls look like an accessory to a door.
    menus = [menu for menu in app.menus if not isinstance(menu, tuple)]
    equal([menu.title for menu in menus], ["Doors & windows", "Walls"],
          "the extension has a menu for each half")
    doors_menu, walls_menu = menus
    doors_entries = [action[0] for action in doors_menu.actions]
    wall_entries = [action[0] for action in walls_menu.actions]
    for wanted in ("Draw a wall…", "Walls panel…", "Take-off…",
                   "Export wall types…", "Import wall types…",
                   "Wall types folder…"):
        check(wanted in wall_entries,
              f"the Walls menu offers {wanted!r}: {wall_entries}")
    for unwanted in ("Place a door or window…", "Edit…", "Erase",
                     "Redraw the swing symbols"):
        check(unwanted not in wall_entries,
              f"and no door command: {unwanted!r} is in the walls menu")
    for unwanted in ("Draw a wall…", "Walls panel…", "Export wall types…",
                     "Import wall types…"):
        check(unwanted not in doors_entries,
              f"the Doors menu has no wall command: {unwanted!r}")
    check("Place a door or window…" in doors_entries,
          "but it does have the door")
    equal(len(app.context_menus), 1, "and a right-click entry")
    equal(len(app.outliner_kinds), 1, "and a Type column for the Browser")

    # ---- every menu entry must actually run ----
    # A lambda in `setup` closes over that function's locals, so a name that was
    # never imported there fails only when the entry is clicked — in the app, in
    # front of the user. The maintainer found exactly that: «Make plan /
    # elevation / 3D» raised NameError: name 'params_mod' is not defined.
    for menu in app.menus:
        if isinstance(menu, tuple):
            continue
        for entry in menu.actions:
            text, call = entry[0], entry[1]
            try:
                call()
            except Exception as exc:                   # noqa: BLE001
                failures.append(f"menu entry {text!r} raised "
                                f"{type(exc).__name__}: {exc}")
    check(True, "every Extensions-menu entry ran")   # counted above

    # The two buttons must be readable. `narrow()` would set Ignored's size
    # policy, and in a row with a stretch that shrinks a button to a 40 px
    # sliver — a button you cannot see is a button you do not have.
    for button, label in ((panel._place, "Place"), (panel._erase, "Erase")):
        check(not button.size_policy_ignored,
              f"the {label} button keeps its own width")
        check(button.minimumWidth() >= 40,
              f"and has room for its label: {button.minimumWidth()}")

    # The interactive tool went in through the guarded shim.
    equal(sorted(window._tools), ["openings_door", "openings_wall"],
          "both tools were registered in the host's tool table")
    check(panel._tool is not None, "and the panel can reach it")
    extension._raise_panel()
    equal(app.shown, app.panels["Openings"], "the menu entry brings the panel up")

    # ---- the wall library, in the Walls panel ----
    # Five languages for the words, whatever libraries exist for the walls: a
    # Dutch build-up read by an English user is still read in English.
    walls_panel = app.panels["Walls"].widget
    library = load("library")
    equal(walls_panel.library_code(), "en-GB",
          "an English app opens on the UK library, which is the point of the "
          "two settings being separate")
    equal(walls_panel.language_code(), "en-GB",
          "and names the walls in the app's language, which is English")
    equal(walls_panel._language_box.count(), 5,
          "every language we have words for is offered")
    equal(walls_panel._library_box.count(), len(library.languages()),
          "and every library we have walls for")

    # Choosing a library is choosing a country, not a language: the Dutch walls
    # are now named in English.
    dutch = walls_panel._library_box.findData("nl")
    walls_panel._library_box.setCurrentIndex(dutch)
    walls_panel._library_box.currentIndexChanged.emit(dutch)
    equal(walls_panel.library_code(), "nl", "the Dutch library is chosen")
    equal(walls_panel.language_code(), "en-GB",
          "and the words did not change with it")
    equal(walls_panel._type.count(), len(library.walls("nl")),
          "the picker lists the whole library, not a combo of two")
    first = walls_panel._type.itemText(0)
    for bit in ("Cavity wall 100-100-100", "300 mm", "3 layers", "reviewed"):
        check(bit in first, f"a type says what it is: {first!r} misses {bit!r}")
    check("draft" in walls_panel._type.itemText(2),
          "and a draft says so")

    # Picking one fills the panel with that build-up.
    index = walls_panel._type.findData("nl.kalkzandsteen.100")
    check(index >= 0, "the picker knows the calcium-silicate wall")
    walls_panel._type.setCurrentIndex(index)
    walls_panel._type.currentIndexChanged.emit(index)
    equal([skin["role"] for skin in walls_panel.draft()["skins"]],
          ["inner_leaf"], "and choosing it takes its skins")

    # Search reads every language, which is the point of the label table.
    walls_panel._search.setText("cavity")
    english = walls_panel._type.count()
    check(0 < english < len(library.walls("nl")),
          f"\"cavity\" narrows the Dutch library to {english} of "
          f"{len(library.walls('nl'))} walls, in English")
    walls_panel._search.setText("spouwmuur")
    equal(walls_panel._type.count(), len(library.search("nl", "spouwmuur")),
          "and \"spouwmuur\" finds what the library says it finds")
    walls_panel._search.setText("zzz")
    equal(walls_panel._type.count(), 0, "nonsense finds nothing")
    walls_panel._search.setText("")
    equal(walls_panel._type.count(), len(library.walls("nl")),
          "clearing the search brings them all back")

    # A language change renames what is on screen, and writes nothing.
    cavity = walls_panel._type.findData("nl.spouwmuur.100-100-100")
    walls_panel._type.setCurrentIndex(cavity)
    walls_panel._type.currentIndexChanged.emit(cavity)
    before = [group.name for group in scene.groups]
    german = walls_panel._language_box.findData("de")
    walls_panel._language_box.setCurrentIndex(german)
    walls_panel._language_box.currentIndexChanged.emit(german)
    equal(walls_panel.language_code(), "de", "the panel is in German now")
    names = [walls_panel._type.itemText(i)
             for i in range(walls_panel._type.count())]
    check(any("Zweischalige Wand" in name for name in names),
          f"and the walls are named in German: {names[:2]}")
    label = walls_panel._skin_rows[0][0].text()
    equal(label, "Außenschale", "the cavity wall's outer leaf, in German")
    equal(walls_panel._skin_rows[0][0].isReadOnly(), True,
          "and a role's name is a translation, not a field to type in")
    equal([group.name for group in scene.groups], before,
          "changing the language changed no geometry")
    english = walls_panel._language_box.findData("en-GB")
    walls_panel._language_box.setCurrentIndex(english)
    walls_panel._language_box.currentIndexChanged.emit(english)
    equal(walls_panel._skin_rows[0][0].text(), "Outer leaf", "and back")

    # ---- a type imported while the app is running is drawable at once ----
    import shutil
    import tempfile
    room = Path(tempfile.mkdtemp(prefix="ingetrazo-walls-panel-"))
    keep = library.USER_HOME
    library.USER_HOME = room
    try:
        mine = {"locale": "nl", "walls": [{
            "key": "nl.kantoor.100",
            "kind": "interior",
            "name": {"nl": "Kantoorwand 100", "en-GB": "Office wall 100"},
            "skins": [{"role": "inner_leaf", "thickness": 100,
                       "material": "Gypsum"}]}]}
        path = room / "office.json"
        path.write_text(json.dumps(mine), encoding="utf-8")
        result = library.import_library(path)
        equal(result["imported"], 1, "the office wall is imported")
        walls_panel.reload_types()
        equal(walls_panel._type.count(), len(library.walls("nl")),
              "the picker shows it without a restart")
        index = walls_panel._type.findData("nl.kantoor.100")
        check(index >= 0, "under its own key")
        walls_panel._type.setCurrentIndex(index)
        walls_panel._type.currentIndexChanged.emit(index)
        equal([skin["material"] for skin in walls_panel.draft()["skins"]],
              ["Gypsum"], "and it is what the next wall would be drawn with")
    finally:
        library.USER_HOME = keep
        library.reset()
        shutil.rmtree(room, ignore_errors=True)
    walls_panel.reload_types()
    equal(walls_panel._type.findData("nl.kantoor.100"), -1,
          "and once the file is gone, so is the wall")

    # The folder the user's own types live in, revealed — the hidden one on
    # macOS, which is why there is a menu entry for it at all.
    reveal = next((action[1] for menu in app.menus
                   if not isinstance(menu, tuple)
                   for action in menu.actions
                   if action[0].startswith("Wall types folder")), None)
    check(reveal is not None, "the menu can reveal the wall types folder")
    reveal()
    check(bool(launched), "and asks the desktop to open it")
    check(str(launched[-1]).endswith("walls"),
          f"the folder the import writes to: {launched[-1]}")

    # ---- import and export, through the menu, with a real file ----
    # The generic loop above cancels every dialog; here one is answered, so the
    # whole path runs: menu entry, file dialog, file, library, picker.
    room = Path(tempfile.mkdtemp(prefix="ingetrazo-walls-menu-"))
    keep = library.USER_HOME
    library.USER_HOME = room / "user"
    exported = room / "dutch.json"
    try:
        def menu_entry(prefix):
            for menu in app.menus:
                if isinstance(menu, tuple):
                    continue
                for text, call in menu.actions:
                    if text.startswith(prefix):
                        return call
            return None

        export = menu_entry("Export wall types")
        check(export is not None, "the extension menu offers an export")
        qt_stubs.QFileDialog.next_path = str(exported)
        export()
        check(exported.is_file(), "and it wrote the file the dialog chose")
        written = json.loads(exported.read_text(encoding="utf-8"))
        here = walls_panel.library_code()
        equal(len(written["walls"]), len(library.walls(here)),
              "with every wall of the library the panel is showing")
        equal(written["locale"], here, "and it says which library it is")

        # The same file back in: nothing new, nothing lost.
        before = len(library.walls(here))
        come_back = menu_entry("Import wall types")
        check(come_back is not None, "and an import to match it")
        qt_stubs.QFileDialog.next_path = str(exported)
        come_back()
        equal(len(library.walls(here)), before,
              "importing what was exported adds no duplicate")
        equal(library.problems(), [], "and leaves no complaint behind")

        # Walls for a country the panel is not showing: it follows them.
        germans = {"locale": "de", "walls": [{
            "key": "de.keller.200", "kind": "interior",
            "name": {"de": "Kellerwand 200", "en-GB": "Cellar wall 200"},
            "skins": [{"role": "structure", "thickness": 200,
                       "material": "Concrete"}]}]}
        german_file = room / "german.json"
        german_file.write_text(json.dumps(germans), encoding="utf-8")
        qt_stubs.QFileDialog.next_path = str(german_file)
        come_back()
        equal(walls_panel.library_code(), "de",
              "an import for another library switches the panel to it")
        equal(walls_panel._type.findData("de.keller.200") >= 0, True,
              "so the imported wall is visible, not merely counted")
    finally:
        qt_stubs.QFileDialog.next_path = None
        library.USER_HOME = keep
        library.reset()
        shutil.rmtree(room, ignore_errors=True)

    # ---- nothing selected: the panel is the next door's settings ----
    panel.refresh()
    check("nothing selected" in panel._status.text().lower()
          or "Nothing selected" in panel._status.text(),
          f"the panel says what it is showing: {panel._status.text()!r}")
    equal(panel._erase.isEnabled(), False,
          "and Erase is off with no door selected")

    # ---- placing: the tool draws a preview, then cuts on the click ----
    tool = panel._tool
    viewport.picked_face = front_face(scene)
    viewport.picked_point = app_stubs.QVector3D(2.0, 0.0, 1.0)
    tool.on_activate(viewport)
    check(viewport.messages, "activating the tool tells the user what to do")

    tool.on_hover(context(viewport, viewport.picked_point))
    preview = tool.preview_faces()
    check(preview, "hovering a wall previews the door before the click")
    check(all(face.attrs for face in preview),
          "the preview faces carry a colour to draw them")

    tool.on_click(context(viewport, viewport.picked_point))
    equal(len(scene.groups), 2,
          "the click made the door and its swing symbol")
    door = next(g for g in scene.groups if g.name.startswith("Door "))
    check(door.ifc and door.ifc.get("class") == "IfcDoor",
          "and it is tagged IfcDoor")
    check("Frame" in [k.name for k in door.children],
          "with its parts")
    check(scene.mesh.is_closed(), "and the wall is still closed")

    # ---- a wall inside a group: the tool must say so, not go quiet ----
    viewport.picked_face = None
    viewport.picked_point = None
    viewport.behind_face = "a face of a grouped wall"
    viewport.messages.clear()
    tool.on_hover(context(viewport, app_stubs.QVector3D(2.0, 0.0, 1.0)))
    check(viewport.messages, "hovering a grouped wall says something")
    check("inside a group" in viewport.messages[-1],
          f"and it says what to do about it: {viewport.messages[-1]!r}")
    check(tool.preview_faces() == [],
          "with no preview, because there is nothing to cut yet")

    # Nothing at all under the cursor: the click explains that too.
    viewport.behind_face = None
    viewport.messages.clear()
    tool.on_click(context(viewport, app_stubs.QVector3D(0.0, 0.0, 0.0)))
    check(viewport.messages, "a click on nothing says something")
    check("Point at a face" in viewport.messages[-1],
          f"and it says where to point: {viewport.messages[-1]!r}")

    # Put the wall back under the cursor for the rest of the test.
    viewport.picked_face = front_face(scene)
    viewport.picked_point = app_stubs.QVector3D(2.0, 0.0, 1.0)

    # ---- the panel shows the door it just placed ----
    equal(panel._item, door, "the panel followed the new door")
    check("Door " in panel._status.text(), f"and names it: "
                                          f"{panel._status.text()!r}")
    check(panel._erase.isEnabled(), "and Erase is available")

    # ---- editing from the panel rebuilds the door ----
    before = [k.name for k in door.children]
    check("Threshold" not in before, "no threshold to begin with")
    panel._editors["threshold"][0].setValue(20.0)      # 20 mm, in mm
    panel._timer.fire()                             # what the debounce calls
    equal(params_mod.normalize(panel._read())["threshold"], 0.02,
          "20 mm in the field is 0.02 m in the parameter")
    check("Threshold" in [k.name for k in door.children],
          "and the threshold part appeared")
    check(viewport.history.last_error is None,
          f"without an error: {viewport.history.last_error}")

    # Handing is a list, and changing it rebuilds the leaf the other way.
    handing = panel._editors["handing"][0]
    index = handing.findData("right")
    check(index >= 0, "handing offers 'right'")
    handing.setCurrentIndex(index)
    handing.currentIndexChanged.emit(index)
    panel._timer.fire()
    equal(params_mod.normalize(panel._read())["handing"], "right",
          "the panel read the choice back")

    # An impossible combination is refused with words, not a traceback.
    panel._editors["width"][0].setValue(300.0)          # 300 mm
    panel._editors["frame_w"][0].setValue(400.0)        # 400 mm of lining
    panel._timer.fire()
    check("clear opening" in panel._status.text(),
          f"and an impossible lining is explained: {panel._status.text()!r}")
    panel._editors["frame_w"][0].setValue(60.0)
    panel._editors["width"][0].setValue(900.0)
    panel._timer.fire()

    # ---- switching to a window ----
    kind_combo = panel._kind
    index = kind_combo.findData("window")
    check(index >= 0, "the panel offers windows")
    kind_combo.setCurrentIndex(index)
    kind_combo.currentIndexChanged.emit(index)
    values = panel._read()
    equal(values["kind"], "window", "the panel is set up for a window now")
    equal(door.ifc.get("class"), "IfcWindow",
          "and the opening in front of it was converted")
    check("sill" in panel._editors, "the form offers a sill")
    check("threshold" not in panel._editors, "and no longer a threshold")
    check(abs(values["sill"] - 0.900) < 1e-9,
          f"standing on 900 mm: {values['sill']}")
    check(abs(values["frame_w"] - 0.067) < 1e-9,
          f"in kozijnhout 67: {values['frame_w']}")
    check(abs(values["frame_depth"] - 0.114) < 1e-9,
          f"114 mm deep: {values['frame_depth']}")
    equal([k.name for k in door.children], ["Frame", "Glass"],
          "a vast raam is a frame and its glass")
    check(scene.mesh.is_closed(), "and the wall is still closed")

    # And a draairaam gets its sash, its 54 × 67 raamhout and its arc.
    type_combo = panel._type
    index = type_combo.findData("swing")
    check(index >= 0, "the panel offers a draairaam")
    type_combo.setCurrentIndex(index)
    type_combo.currentIndexChanged.emit(index)
    values = panel._read()
    equal(values["type"], "swing", "the type followed")
    check(abs(values["sash_w"] - 0.054) < 1e-9, "raamhout 54 mm")
    check(abs(values["sash_d"] - 0.067) < 1e-9, "67 mm deep")
    equal([k.name for k in door.children], ["Frame", "Sash", "Glass"],
          "and now there is a sash to open")
    check(object_mod.symbol_group(scene, door) is not None,
          "with a swing symbol for the plan")
    check(scene.mesh.is_closed(), "and the wall is still closed")

    # ---- scenes ----
    made = scenes_mod.make(viewport, params_mod.SYMBOL_LAYER)
    equal(sorted(made), ["3D", "Elevation", "Plan"],
          "the three scenes are made")
    equal([view.name for view in scene.saved_views], list(made),
          "and they are in the document")
    plan = next(v for v in scene.saved_views if v.name == "Plan")
    equal(plan.hidden_layers, [],
          "a plan shows the swing symbol (its layer is not hidden)")
    three_d = next(v for v in scene.saved_views if v.name == "3D")
    check(params_mod.SYMBOL_LAYER in three_d.hidden_layers,
          "and a 3D view hides it")
    # Making them again replaces rather than piles up.
    scenes_mod.make(viewport, params_mod.SYMBOL_LAYER)
    equal(len(scene.saved_views), 3, "remaking replaces, it does not stack")

    # ---- erasing ----
    panel._on_erase()
    equal([g for g in scene.groups if g.name.startswith("Door ")], [],
          "the door is gone")
    check(scene.mesh.is_closed(), "the wall is closed again")
    equal(params_mod.KEY not in scene.plugin_data, True,
          "and the empty bookkeeping went with it")

    # ---- undo all the way ----
    while viewport.history.undo():
        pass
    equal(scene.saved_views, [], "undo takes the scenes away too")
    equal(len(scene.groups), 0, "and the doors")
    check(scene.mesh.is_closed(), "and the wall stands as it began")

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"openings panel: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
