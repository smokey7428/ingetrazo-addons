# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Stand-ins for the parts of IngeTrazo an extension builds document objects
with: the vector maths, the mesh, groups, materials, layers, the scene and the
undo stack.

The **vectors are real**. ``QVector3D``'s dot, cross and normalise are the whole
of the opening arithmetic, so a stub that approximated them would test nothing.
Everything else is as small as it can be and still behave:

* ``Mesh`` welds vertices **by position**, like the real one, so ``add_hole``,
  ``remove_hole`` and a closed-surface test all mean something;
* ``Mesh.capture_state`` returns values, not object identities. The real one
  keeps identity so a command holding references stays valid; here only the
  *set of geometry* has to come back, which is what an undo test checks. Worth
  knowing: a test that undoes and then keeps working with a face object is
  testing something this stub does not model.
"""
from __future__ import annotations

import abc
import math
import sys
import types


# ---- vector maths -----------------------------------------------------------
class QVector3D:
    __slots__ = ("_x", "_y", "_z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self._x, self._y, self._z = float(x), float(y), float(z)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def z(self) -> float:
        return self._z

    def toTuple(self) -> tuple:
        return (self._x, self._y, self._z)

    def length(self) -> float:
        return math.sqrt(self._x ** 2 + self._y ** 2 + self._z ** 2)

    def normalized(self) -> "QVector3D":
        n = self.length()
        return QVector3D() if n < 1e-12 else QVector3D(self._x / n,
                                                      self._y / n,
                                                      self._z / n)

    def normalize(self) -> None:
        """In place, like Qt's."""
        n = self.length()
        if n >= 1e-12:
            self._x, self._y, self._z = self._x / n, self._y / n, self._z / n

    @staticmethod
    def dotProduct(a, b) -> float:
        return a._x * b._x + a._y * b._y + a._z * b._z

    @staticmethod
    def crossProduct(a, b) -> "QVector3D":
        return QVector3D(a._y * b._z - a._z * b._y,
                         a._z * b._x - a._x * b._z,
                         a._x * b._y - a._y * b._x)

    def __add__(self, other):
        return QVector3D(self._x + other._x, self._y + other._y,
                         self._z + other._z)

    __radd__ = __add__

    def __sub__(self, other):
        return QVector3D(self._x - other._x, self._y - other._y,
                         self._z - other._z)

    def __neg__(self):
        return QVector3D(-self._x, -self._y, -self._z)

    def __mul__(self, k):
        if isinstance(k, (int, float)):
            return QVector3D(self._x * k, self._y * k, self._z * k)
        return QVector3D(self._x * k._x, self._y * k._y, self._z * k._z)

    __rmul__ = __mul__

    def __repr__(self):
        return f"QVector3D({self._x:g}, {self._y:g}, {self._z:g})"


class QVector4D:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=0.0):
        self.x, self.y, self.z, self.w = float(x), float(y), float(z), float(w)


class QMatrix4x4:
    """A 4x4 built from columns, as the extension builds it — so the mapping
    down here is the same arithmetic, not Qt's storage order."""

    def __init__(self, *args):
        self._cols = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        if len(args) == 1 and isinstance(args[0], QMatrix4x4):
            self._cols = [list(c) for c in args[0]._cols]

    def setColumn(self, index: int, v: QVector4D) -> None:
        self._cols[index] = [v.x, v.y, v.z, v.w]

    def column(self, index: int) -> list:
        return list(self._cols[index])

    def map(self, point: QVector3D) -> QVector3D:
        cols = self._cols
        return QVector3D(
            cols[0][0] * point.x() + cols[1][0] * point.y()
            + cols[2][0] * point.z() + cols[3][0],
            cols[0][1] * point.x() + cols[1][1] * point.y()
            + cols[2][1] * point.z() + cols[3][1],
            cols[0][2] * point.x() + cols[1][2] * point.y()
            + cols[2][2] * point.z() + cols[3][2])

    def mapVector(self, v: QVector3D) -> QVector3D:
        cols = self._cols
        return QVector3D(cols[0][0] * v.x() + cols[1][0] * v.y()
                         + cols[2][0] * v.z(),
                         cols[0][1] * v.x() + cols[1][1] * v.y()
                         + cols[2][1] * v.z(),
                         cols[0][2] * v.x() + cols[1][2] * v.y()
                         + cols[2][2] * v.z())


# ---- the mesh ---------------------------------------------------------------
class Vertex:
    def __init__(self, position: QVector3D):
        self.position = position


class Edge:
    def __init__(self, v0, v1):
        self.v0, self.v1 = v0, v1
        self.layer = None
        self.hidden = False
        self.curve = None
        self.soft = False
        self.faces: list = []


class Face:
    def __init__(self, loop, holes=()):
        self.loop = list(loop)
        self.hole_loops = [list(h) for h in holes]
        self.attrs: dict = {}
        self.layer = None
        self.interior = False

    def normal(self) -> QVector3D:
        n = QVector3D()
        count = len(self.loop)
        for i in range(count):
            a, b = self.loop[i].position, self.loop[(i + 1) % count].position
            n = n + QVector3D((a.y() - b.y()) * (a.z() + b.z()),
                              (a.z() - b.z()) * (a.x() + b.x()),
                              (a.x() - b.x()) * (a.y() + b.y()))
        return n

    def centroid(self) -> QVector3D:
        total = QVector3D()
        for v in self.loop:
            total = total + v.position
        return total * (1.0 / max(len(self.loop), 1))

    def corner_set(self) -> frozenset:
        return frozenset((round(v.position.x(), 6), round(v.position.y(), 6),
                          round(v.position.z(), 6)) for v in self.loop)


class Mesh:
    """Vertices weld by position, as the real mesh does — which is what makes
    a hole and a closed-surface test mean anything."""

    def __init__(self):
        self.vertices: list = []
        self.edges: list = []
        self.faces: list = []

    def vertex(self, point: QVector3D) -> Vertex:
        key = (round(point.x(), 6), round(point.y(), 6), round(point.z(), 6))
        for v in self.vertices:
            if (round(v.position.x(), 6), round(v.position.y(), 6),
                    round(v.position.z(), 6)) == key:
                return v
        made = Vertex(QVector3D(*point.toTuple()))
        self.vertices.append(made)
        return made

    def add_face(self, loop_positions, hole_loops=None) -> Face:
        face = Face([self.vertex(p) for p in loop_positions],
                    [[self.vertex(p) for p in h] for h in (hole_loops or ())])
        self.faces.append(face)
        return face

    def add_hole(self, face, loop_positions) -> list:
        loop = [self.vertex(p) for p in loop_positions]
        face.hole_loops.append(loop)
        return loop

    def remove_hole(self, face, loop) -> None:
        if loop in face.hole_loops:
            face.hole_loops.remove(loop)

    def remove_face(self, face) -> None:
        if face in self.faces:
            self.faces.remove(face)

    def add_edge(self, a: QVector3D, b: QVector3D) -> Edge:
        v0, v1 = self.vertex(a), self.vertex(b)
        for e in self.edges:
            if {id(e.v0), id(e.v1)} == {id(v0), id(v1)}:
                return e
        made = Edge(v0, v1)
        self.edges.append(made)
        return made

    # ---- value snapshots (see the module docstring) ----
    def capture_state(self) -> dict:
        def ring(loop):
            return [v.position.toTuple() for v in loop]
        return {"faces": [(ring(f.loop), [ring(h) for h in f.hole_loops],
                           dict(f.attrs), f.layer) for f in self.faces],
                "edges": [((e.v0.position.toTuple(), e.v1.position.toTuple()),
                           e.layer) for e in self.edges]}

    def restore_state(self, snap: dict) -> None:
        self.vertices.clear()
        self.edges.clear()
        self.faces.clear()
        for loop, holes, attrs, layer in snap["faces"]:
            face = self.add_face([QVector3D(*p) for p in loop],
                                 [[QVector3D(*p) for p in h] for h in holes])
            face.attrs = dict(attrs)
            face.layer = layer
        for (a, b), layer in snap["edges"]:
            edge = self.add_edge(QVector3D(*a), QVector3D(*b))
            edge.layer = layer

    def is_closed(self) -> bool:
        """Every edge of the loose mesh borders exactly two faces — the test
        ``core/bim.py`` applies before it will report a volume."""
        counts: dict = {}
        for face in self.faces:
            for ring in (face.loop, *face.hole_loops):
                n = len(ring)
                for i in range(n):
                    a, b = ring[i], ring[(i + 1) % n]
                    key = frozenset((id(a), id(b)))
                    counts[key] = counts.get(key, 0) + 1
        return bool(counts) and all(c == 2 for c in counts.values())


# ---- groups, materials, layers ---------------------------------------------
class Group:
    def __init__(self, mesh=None, name: str | None = None):
        self.mesh = mesh if mesh is not None else Mesh()
        self.name = name or "Group"
        self.children: list = []
        self.ifc = None
        self.ext: dict | None = None
        self.xform = None
        self.layer = None
        self.hidden = False
        self.component = False
        self.uid = f"uid{id(self):x}"

    def adopt(self, parts) -> None:
        self.children = list(parts)

    def is_component(self) -> bool:
        return bool(self.component)


class Material:
    def __init__(self, name, color=(1, 1, 1), opacity=1.0, texture=None):
        self.name, self.color, self.opacity = name, tuple(color), opacity
        self.texture = texture

    def face_attrs(self) -> dict:
        attrs = {"color": tuple(self.color), "mat": self.name}
        if self.opacity < 1.0:
            attrs["opacity"] = self.opacity
        return attrs


class Layer:
    def __init__(self, name, visible=True, locked=False):
        self.name, self.visible, self.locked = name, visible, locked


class Scene:
    def __init__(self):
        self.mesh = Mesh()
        self.groups: list = []
        self.layers: list = [Layer("Layer0")]
        self.materials: dict = {}
        self.plugin_data: dict = {}
        self.selection: set = set()
        self.version = 0
        self.view_version = 0
        self.dimensions: list = []
        self.text_labels: list = []
        self.guides: list = []
        self.saved_views: list = []
        self.active_ifc = None
        self.section_planes: list = []

    class _Loose:
        def __init__(self, mesh):
            self.faces = mesh.faces

    @property
    def loose_mesh(self):
        return self.mesh

    def entity_visible(self, entity) -> bool:
        from core.layers import layer_of
        name = layer_of(entity)
        if name is not None:
            for ly in self.layers:
                if ly.name == name:
                    return ly.visible
        return True


class History:
    def __init__(self, scene):
        self._scene = scene
        self.undo_stack: list = []
        self.redo_stack: list = []
        self.last_error = None
        self.last_rejected = None

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
        self.messages: list = []

    def update(self) -> None:
        pass

    def notify_scene_changed(self) -> None:
        pass

    def flash_status(self, text, msec=2500) -> None:
        self.messages.append(text)


def install() -> None:
    """Register ``core.*`` and the Qt geometry classes an extension imports."""
    def module(name, **attrs):
        made = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(made, key, value)
        return made

    core = module("core")
    core.__path__ = []
    sys.modules["core"] = core

    mesh_mod = module("core.mesh", Mesh=Mesh, Face=Face, Edge=Edge,
                      Vertex=Vertex)
    sys.modules["core.mesh"] = mesh_mod
    group_mod = module("core.group", Group=Group)
    sys.modules["core.group"] = group_mod
    mats_mod = module("core.materials", Material=Material)
    sys.modules["core.materials"] = mats_mod

    def layer_of(entity):
        return getattr(entity, "layer", None)

    sys.modules["core.layers"] = module("core.layers", Layer=Layer,
                                        layer_of=layer_of)

    history_mod = module("core.history")

    class Command(abc.ABC):
        @abc.abstractmethod
        def do(self, scene):
            """apply"""

        @abc.abstractmethod
        def undo(self, scene):
            """reverse"""

    history_mod.Command = Command
    sys.modules["core.history"] = history_mod

    # ---- what the panel and the scenes import ----
    i18n = module("core.i18n", current_language=lambda: "en", tr=lambda s, **k: s)
    sys.modules["core.i18n"] = i18n

    @__import__("dataclasses").dataclass
    class PreviewFace:
        """``core.geometry.Face`` — the light polygon a tool previews with."""
        vertices: list
        holes: list
        attrs: dict | None = None

        def __init__(self, vertices=None, holes=None, attrs=None):
            self.vertices = list(vertices or [])
            self.holes = [list(h) for h in (holes or ())]
            self.attrs = attrs

    sys.modules["core.geometry"] = module("core.geometry", Face=PreviewFace)

    saved = module("core.saved_views")

    class SavedView:
        def __init__(self, name, **state):
            self.name = name
            self.__dict__.update(state)

        @classmethod
        def capture(cls, name, scene, camera):
            return cls(name,
                       hidden_layers=[ly.name for ly in scene.layers
                                      if not ly.visible],
                       yaw=camera.yaw, pitch=camera.pitch,
                       perspective=getattr(camera, "perspective", True))

        def apply(self, scene, camera=None):
            hidden = set(self.hidden_layers or ())
            for layer in scene.layers:
                layer.visible = layer.name not in hidden
            if camera is not None:
                camera.yaw, camera.pitch = self.yaw, self.pitch

    saved.SavedView = SavedView
    sys.modules["core.saved_views"] = saved

    # SnapshotImport: tracks the views and layers a mutation added, so undo
    # takes them away again — the behaviour the scenes rely on.
    class SnapshotImport(Command):
        def __init__(self, mutate):
            self.mutate = mutate
            self.before: dict | None = None
            self.after: dict | None = None
            self.added_views: list = []
            self.added_layers: list = []

        def do(self, scene):
            if self.after is None:
                views = list(scene.saved_views)
                layers = list(scene.layers)
                self.before = scene.mesh.capture_state()
                self.mutate(scene)
                self.after = scene.mesh.capture_state()
                self.added_views = [v for v in scene.saved_views
                                    if v not in views]
                self.added_layers = [ly for ly in scene.layers
                                     if ly not in layers]
            else:
                scene.mesh.restore_state(self.after)
            scene.version += 1

        def undo(self, scene):
            if self.before is not None:
                scene.mesh.restore_state(self.before)
            for view in self.added_views:
                if view in scene.saved_views:
                    scene.saved_views.remove(view)
            for layer in self.added_layers:
                if layer in scene.layers:
                    scene.layers.remove(layer)
            scene.version += 1

    history_mod.SnapshotImport = SnapshotImport

    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QVector3D = QVector3D
    qtgui.QVector4D = QVector4D
    qtgui.QMatrix4x4 = QMatrix4x4
    sys.modules["PySide6.QtGui"] = qtgui
