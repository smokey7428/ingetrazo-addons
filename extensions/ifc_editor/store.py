# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Where an element's IFC fields live, and how they are written.

Two storages, on purpose:

* **The class and the name stay in IngeTrazo's own BIM tag** — a face's
  ``attrs["ifc"]``, a group's ``ifc``. That is the core's tag, read by the BIM
  panel, the take-off, the CSV bridge and the core's IFC export. Keeping it
  authoritative means our extension never makes IngeTrazo's own panels
  disagree with what the user sees here.
* **Everything else is ours**, in ``scene.plugin_data["ifc_editor"]``: the
  description, object type, tag, global id, predefined type, every property
  set. The core has nowhere to put these — it writes ``Description``,
  ``ObjectType``, ``PredefinedType`` and all ``Pset_*`` as ``$`` — and one
  JSON-safe value per extension is the storage the plugin API offers.

An edit touches both, so it goes through **one** command rather than two: the
project treats a single undo step per user action as non-negotiable, and
``set_document_data`` alone would be a second step.

Identity is the thing that has to survive a save and a reopen:

* a group is ``group.uid`` — persisted in the .igz;
* a loose-face object is the id in its IFC tag, the same id the core assigns.

Both are re-resolved at write time rather than held as references, so an edit
still lands where it should after a group is reopened or the mesh is rebuilt.
"""
from __future__ import annotations

from core.group import Group
from core.history import Command
from core.mesh import Face

#: This extension's key in ``scene.plugin_data`` — also ``app.key``.
KEY = "ifc_editor"

#: The schema assumed for an element that has never said which one it is.
DEFAULT_SCHEMA = "IFC4"


# ---- identity ---------------------------------------------------------------
def object_key(entity) -> str | None:
    """The stable key of an element that is already an IFC object, else None.

    ``uid:<group.uid>`` for a *tagged* group, ``ifc:<object id>`` for the loose
    faces sharing one BIM tag. Having a uid is not enough: the tag is what makes
    a group an IFC object, the same rule the core's BIM panel and take-off go
    by. An untagged element has identity but is not an IFC object yet, and this
    extension edits IFC objects.
    """
    if isinstance(entity, Group):
        if not getattr(entity, "ifc", None):
            return None
        uid = getattr(entity, "uid", None)
        return f"uid:{uid}" if uid else None
    if isinstance(entity, Face):
        tag = entity.attrs.get("ifc")
        if isinstance(tag, dict) and tag.get("id") is not None:
            return f"ifc:{tag['id']}"
    return None


def resolve(scene, key: str) -> tuple[list, list]:
    """``(faces, groups)`` for ``key`` — what an edit has to touch.

    Re-resolved from the scene every time, never remembered: the same object
    after a group is reopened or the mesh is rebuilt is still the same key.
    """
    kind, _, ident = str(key).partition(":")
    if kind == "uid":
        return [], [g for g in scene.groups
                    if str(getattr(g, "uid", "")) == ident]
    if kind == "ifc":
        try:
            wanted = int(ident)
        except ValueError:
            return [], []
        return [f for f in scene.loose_mesh.faces
                if (f.attrs.get("ifc") or {}).get("id") == wanted], []
    return [], []


def object_id(scene, key: str) -> str | None:
    """The display identity of ``key`` in the scene, or None when it is gone."""
    faces, groups = resolve(scene, key)
    if groups:
        return getattr(groups[0], "name", None) or "(group)"
    if faces:
        tag = faces[0].attrs.get("ifc") or {}
        return tag.get("name") or "(faces)"
    return None


# ---- reading ----------------------------------------------------------------
def _write_plugin_data(scene, data: dict) -> None:
    """Store this extension's value, or take the key away when there is
    nothing left to store.

    An empty ``{}`` under our key is not the same as no key at all: the core
    asks whether ``scene.plugin_data`` is empty to decide if a document has
    anything in it, so leaving a hollow entry behind would make an empty
    document look used. ``SetPluginDataCommand`` settles for the same
    convention.
    """
    if data:
        scene.plugin_data[KEY] = data
    else:
        scene.plugin_data.pop(KEY, None)


def plugin_data(scene) -> dict:
    """This extension's value in the document, or ``{}``. Never None."""
    data = (getattr(scene, "plugin_data", None) or {}).get(KEY)
    return data if isinstance(data, dict) else {}


def stored(scene, key: str) -> dict:
    """The fields we hold for ``key``, or ``{}``. A copy: write with
    :func:`edit`, never in place."""
    entry = (plugin_data(scene).get("objects") or {}).get(str(key))
    if not isinstance(entry, dict):
        return {}
    import json
    return json.loads(json.dumps(entry))


def record(scene, entity) -> dict | None:
    """Everything known about the IFC object ``entity`` belongs to, or None
    when it is not one yet.

    ``class`` and ``name`` come from the core tag — the source of truth —
    while the rest comes from our own storage.
    """
    key = object_key(entity)
    if key is None:
        return None
    if isinstance(entity, Group):
        ifc_class, name = ((entity.ifc or {}).get("class"),
                           (entity.ifc or {}).get("name"))
    else:
        tag = entity.attrs.get("ifc") or {}
        ifc_class, name = tag.get("class"), tag.get("name")
    data = stored(scene, key)
    return {
        "key": key,
        "class": ifc_class or "",
        "name": name or "",
        "schema": data.get("schema") or DEFAULT_SCHEMA,
        "fields": dict(data.get("fields") or {}),
        "psets": dict(data.get("psets") or {}),
        "pset_types": dict(data.get("pset_types") or {}),
        "custom": [str(n) for n in (data.get("custom") or [])],
        "tagged": True,
    }


def records(scene) -> list[dict]:
    """Every IFC object in the document, as :func:`record` would see it."""
    from core.bim import collect_objects
    out: list[dict] = []
    for obj in collect_objects(scene):
        faces, group = obj.get("faces"), obj.get("group")
        entity = group if group is not None else (faces[0] if faces else None)
        if entity is None:
            continue
        entry = record(scene, entity)
        if entry is not None:
            out.append(entry)
    return out


# ---- writing ----------------------------------------------------------------
class EditIfcObject(Command):
    """Change one IFC object's fields, as ONE undo step.

    ``fields``, ``psets`` and ``custom`` replace what we store; ``ifc_class``
    and ``name`` (when given) also rewrite the core tag, so the BIM panel, the
    take-off and the core's export follow along. Anything not passed is left
    alone.

    Both the previous plugin data and the previous core tag are kept, so undo
    restores exactly what was there — including clearing the tag again, which
    the mesh snapshot alone would not do for a group.
    """

    def __init__(self, key: str, *, fields: dict | None = None,
                 psets: dict | None = None, pset_types: dict | None = None,
                 custom: list | None = None, schema: str | None = None,
                 ifc_class: str | None = None, name: str | None = None) -> None:
        self.key = str(key)
        self.fields = fields
        self.psets = psets
        self.pset_types = pset_types
        self.custom = custom
        self.schema = schema
        self.ifc_class = ifc_class
        self.name = name
        self._before_data: dict | None = None
        self._before_tag = None

    # -- helpers --
    def _snapshot(self, scene) -> tuple[dict, list]:
        import json
        before_data = json.loads(json.dumps(plugin_data(scene)))
        faces, groups = resolve(scene, self.key)
        before_tag: list = []
        for group in groups:
            before_tag.append(("group", group,
                               dict(group.ifc) if group.ifc else None))
        for face in faces:
            tag = face.attrs.get("ifc")
            before_tag.append(("face", face, dict(tag) if tag else None))
        return before_data, before_tag

    def _apply(self, scene, previous: tuple[dict, list]) -> None:
        import json
        before_data, before_tag = previous

        entry = dict((before_data.get("objects") or {}).get(self.key) or {})
        if self.schema is not None:
            entry["schema"] = self.schema
        if self.fields is not None:
            entry["fields"] = json.loads(json.dumps(self.fields))
        if self.psets is not None:
            entry["psets"] = json.loads(json.dumps(self.psets))
        if self.pset_types is not None:
            entry["pset_types"] = json.loads(json.dumps(self.pset_types))
        if self.custom is not None:
            entry["custom"] = list(self.custom)

        data = dict(before_data)
        objects = dict(data.get("objects") or {})
        objects[self.key] = entry
        data["objects"] = objects
        _write_plugin_data(scene, data)

        if self.ifc_class is not None or self.name is not None:
            faces, groups = resolve(scene, self.key)
            for group in groups:
                current = dict(group.ifc or {})
                if self.ifc_class is not None:
                    current["class"] = self.ifc_class
                if self.name is not None:
                    current["name"] = self.name
                group.ifc = current
            for face in faces:
                current = dict(face.attrs.get("ifc") or {})
                if self.ifc_class is not None:
                    current["class"] = self.ifc_class
                if self.name is not None:
                    current["name"] = self.name
                face.attrs["ifc"] = current

        scene.version += 1

    # -- Command --
    def do(self, scene) -> None:
        self._before_data, self._before_tag = self._snapshot(scene)
        self._apply(scene, (self._before_data, self._before_tag))

    def undo(self, scene) -> None:
        if self._before_data is None:
            return
        _write_plugin_data(scene, self._before_data)
        for kind, entity, tag in self._before_tag:
            if kind == "group":
                entity.ifc = tag
            else:
                if tag is None:
                    entity.attrs.pop("ifc", None)
                else:
                    entity.attrs["ifc"] = tag
        scene.version += 1


def edit(viewport, key: str, **changes):
    """Run an :class:`EditIfcObject` and refresh — the one way to write.

    Through the command layer, so it is undoable; then notified, so the tray,
    the title bar and the panel all catch up.
    """
    command = EditIfcObject(key, **changes)
    viewport.history.execute(command)
    notify = getattr(viewport, "notify_scene_changed", None)
    if callable(notify):
        notify()
    viewport.update()
    return command
