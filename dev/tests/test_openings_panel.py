#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
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
    full = f"ingetrazo_plugin_openings.{name}"
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

    scene = app_stubs.Scene()
    wall(scene)
    viewport = FakeViewport(scene)
    window = FakeWindow()
    app = FakeApp(scene, viewport, window)

    # ---- setup(app) ----
    extension.setup(app)
    equal(list(app.panels), ["Openings"], "setup adds the Openings panel")
    panel = app.panels["Openings"].widget
    check(panel._dock is not None, "the panel knows its own tab")
    check(bool(app.menus), "and the extension has its own submenu")
    equal(len(app.context_menus), 1, "and a right-click entry")
    equal(len(app.outliner_kinds), 1, "and a Type column for the Browser")

    # The interactive tool went in through the guarded shim.
    equal(list(window._tools), [tool_mod.TOOL_KEY],
          "the door tool was registered in the host's tool table")
    check(panel._tool is not None, "and the panel can reach it")
    extension._raise_panel()
    equal(app.shown, app.panels["Openings"], "the menu entry brings the panel up")

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
