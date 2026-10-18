# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Write the document as IFC — every field you edited, and the walls' openings.

The core has its own IFC writer (``formats/ifc.py``) and it is good at what it
does, but it writes a **fixed, narrow set**: GlobalId, Name, Tag, geometry and
the ``Qto_*`` quantities, with ``Description``, ``ObjectType``,
``PredefinedType``, ``OperationType`` and every ``Pset_*`` as ``$``. That is why
this extension exists, and why it needs its own writer: fields you edited that
never reach the file are fields you did not edit.

What makes this writer different is that it does not hardcode anything. The
**schema tables** say, for each IFC class, exactly which attributes there are,
in which order, and what type each holds — so an element is emitted with the
right number of attributes and the right literal for each, for *any* of the 776
classes, without a table of counts to keep in step.

It also writes what the core cannot know about: the **openings** in a wall of
ours. Each becomes an ``IfcOpeningElement`` with its own geometry,
``IfcRelVoidsElement`` to the wall, and — where a door or window stands in it —
``IfcRelFillsElement``. That is how IFC expects a hole to be described, and it
is the reason a wall can stay a wall.

IFC4 only for now: IFC2X3 names several classes differently (``IfcWallStandardCase``
and friends) and keeps ``PredefinedType`` on the *type* entities, and the
tables are ready for it — the entity vocabulary is the next step, not the layout.
"""
from __future__ import annotations

import datetime
import math
import uuid
from pathlib import Path

from . import schema as schema_mod
from . import store

#: The IFC alphabet, for a 22-character compressed GUID.
_GUID_CHARS = ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "abcdefghijklmnopqrstuvwxyz_$")

#: Value kinds the writer has to format differently in a STEP file.
_NUMBERS = ("integer", "real", "number")

#: The key the ``openings`` extension keeps a wall's own parameters under.
#: The writer reads the *document*, not that extension's code: a wall's
#: openings and a hosted window's host id are data in the .igz, so this is a
#: name to agree on, not an import.
OPENINGS_KEY = "openings"


def guid() -> str:
    """A fresh, 22-character IFC compressed GUID."""
    number = uuid.uuid4().int
    return "".join(_GUID_CHARS[(number >> (6 * i)) & 63]
                   for i in range(21, -1, -1))


def _s(text: str) -> str:
    """An IFC string literal: apostrophes doubled, non-ASCII as ``\\X2\\…``."""
    out: list = []
    run: list = []

    def flush():
        if run:
            out.append("\\X2\\" + "".join(f"{ord(c):04X}" for c in run)
                       + "\\X0\\")
            run.clear()

    for ch in str(text):
        if ord(ch) < 128:
            flush()
            out.append("''" if ch == "'" else ch)
        else:
            run.append(ch)
    flush()
    return "'" + "".join(out) + "'"


def _f(value: float) -> str:
    return f"{float(value):.6f}"


class _Step:
    """The lines of a STEP file, numbered as they are added."""

    def __init__(self) -> None:
        self.lines: list = []
        self._next = 1

    def add(self, entity: str, *attrs) -> int:
        eid = self._next
        self._next += 1
        self.lines.append(f"#{eid}={entity.upper()}({','.join(attrs)});")
        return eid


# ---- values -----------------------------------------------------------------
def literal(kind: str, value) -> str:
    """``value`` as a STEP literal of ``kind``'s type, or ``$`` for nothing.

    The kind comes from the schema table (``Table.resolve_kind``), which is what
    lets one function format a label, a measure, an enumeration and a boolean
    correctly without a list of IFC types.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return "$"
    if kind == "boolean":
        if isinstance(value, str):
            return ".T." if value.strip().lower() in ("true", "1", "yes") else ".F."
        return ".T." if value else ".F."
    if kind == "enum":
        return "." + str(value).strip().upper().replace(" ", "_") + "."
    if kind in _NUMBERS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "$"
        if not math.isfinite(number):
            return "$"
        return str(int(number)) if kind == "integer" else _f(number)
    return _s(str(value))


# ---- geometry ---------------------------------------------------------------
def _points(step: _Step, cache: dict, corners) -> list:
    """Cartesian points for a loop of vertices (or of plain coordinates)."""
    ids = []
    for corner in corners:
        point = getattr(corner, "position", corner)
        if hasattr(point, "x"):
            key = (round(point.x(), 6), round(point.y(), 6), round(point.z(), 6))
        else:
            key = tuple(round(float(c), 6) for c in point)
        found = cache.get(key)
        if found is None:
            found = step.add("IFCCARTESIANPOINT",
                             f"({_f(key[0])},{_f(key[1])},{_f(key[2])})")
            cache[key] = found
        ids.append(found)
    return ids


def _components(faces) -> list:
    """The face set split into connected solids, by shared corners.

    A multi-skin wall — or a skin cut into blocks by its openings — is several
    solids, not one. An ``IfcClosedShell`` is meant to be a single connected
    manifold, so each solid gets its own brep and the representation lists them
    all: that is how IFC describes an element made of parts.
    """
    parent = list(range(len(faces)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    owner: dict = {}
    for index, (loop, holes) in enumerate(faces):
        for ring in (loop, *holes):
            for corner in ring:
                point = getattr(corner, "position", corner)
                key = (round(point.x(), 6), round(point.y(), 6),
                       round(point.z(), 6)) if hasattr(point, "x") else \
                    tuple(round(float(c), 6) for c in point)
                if key in owner:
                    union(index, owner[key])
                else:
                    owner[key] = index

    groups: dict = {}
    for index in range(len(faces)):
        groups.setdefault(find(index), []).append(index)
    return [groups[key] for key in groups]


def brep(step: _Step, faces, context: int) -> int:
    """Faceted geometry for a face set → an ``IFCSHAPEREPRESENTATION`` id.

    One ``IfcFacetedBrep`` per connected solid, listed together in the
    representation's items — so a wall of skins, or a skin in blocks around its
    openings, is written the way IFC expects a compound body.
    """
    items = [_solid(step, [faces[i] for i in group])
             for group in _components(faces)]
    return step.add("IFCSHAPEREPRESENTATION", f"#{context}", "'Body'",
                    "'Brep'", "(" + ",".join(f"#{i}" for i in items) + ")")


def _solid(step: _Step, faces) -> int:
    """One connected solid → an ``IFCFACETEDBREP`` id."""
    cache: dict = {}
    ids = []
    for loop, holes in faces:
        bounds = []
        outer = step.add("IFCPOLYLOOP",
                         "(" + ",".join(f"#{i}"
                                        for i in _points(step, cache, loop))
                         + ")")
        bounds.append(f"#{step.add('IFCFACEOUTERBOUND', f'#{outer}', '.T.')}")
        for hole in holes:
            inner = step.add("IFCPOLYLOOP",
                             "(" + ",".join(f"#{i}" for i in
                                            _points(step, cache, hole)) + ")")
            bounds.append(f"#{step.add('IFCFACEBOUND', f'#{inner}', '.T.')}")
        ids.append(step.add("IFCFACE", "(" + ",".join(bounds) + ")"))
    shell = step.add("IFCCLOSEDSHELL",
                     "(" + ",".join(f"#{i}" for i in ids) + ")")
    return step.add("IFCFACETEDBREP", f"#{shell}")


def _box(corners) -> list:
    """A closed box from eight corners, wound outward: ``(loop, holes)`` faces."""
    def loop(*indexes):
        return [corners[i] for i in indexes]

    return [(loop(0, 3, 2, 1), []), (loop(4, 5, 6, 7), []),
            (loop(0, 1, 5, 4), []), (loop(1, 2, 6, 5), []),
            (loop(2, 3, 7, 6), []), (loop(3, 0, 4, 7), [])]


# ---- the walls' openings ----------------------------------------------------
def _wall_data(group) -> dict | None:
    """The wall's own parameters, read from the document (no import needed)."""
    ext = getattr(group, "ext", None) or {}
    found = ext.get(OPENINGS_KEY) if isinstance(ext, dict) else None
    if isinstance(found, dict) and found.get("kind") == "wall":
        return found
    return None


def opening_faces(w: dict, opening: dict) -> list:
    """The opening as a closed box through the wall — its own IFC geometry."""
    path = w.get("path") or []
    index = int(opening.get("segment", 0))
    if index < 0 or index + 1 >= len(path):
        return []
    a, b = path[index], path[index + 1]
    delta = (b[0] - a[0], b[1] - a[1])
    length = math.hypot(*delta)
    if length < 1e-9:
        return []
    d = (delta[0] / length, delta[1] / length)
    n = (-d[1], d[0])
    half = sum(float(s.get("thickness", 0.0))
               for s in w.get("skins") or ()) * 0.5
    base = float(w.get("base", 0.0))
    s0 = float(opening.get("start", 0.0))
    s1 = s0 + float(opening.get("width", 0.0))
    z0 = base + float(opening.get("sill", 0.0))
    z1 = z0 + float(opening.get("height", 0.0))

    def at(s, offset, z):
        return (a[0] + d[0] * s + n[0] * offset,
                a[1] + d[1] * s + n[1] * offset, z)

    corners = [at(s0, -half, z0), at(s1, -half, z0),
               at(s1, half, z0), at(s0, half, z0),
               at(s0, -half, z1), at(s1, -half, z1),
               at(s1, half, z1), at(s0, half, z1)]
    return _box(corners)


# ---- the file ---------------------------------------------------------------
def save(scene, path, project_name: str = "IngeTrazo project",
         schema: str = "IFC4") -> int:
    """Write every tagged object to ``path``. Returns how many elements.

    Raises ``ValueError`` when nothing is tagged — an IFC file with no elements
    is not a document, it is a mistake.
    """
    from core.bim import class_quantities, collect_objects

    table = schema_mod.load(schema)
    objects = collect_objects(scene)
    if not objects:
        raise ValueError("No tagged BIM objects to export")

    step = _Step()
    origin = step.add("IFCCARTESIANPOINT", "(0.,0.,0.)")
    axis = step.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
    context = step.add("IFCGEOMETRICREPRESENTATIONCONTEXT",
                       "$", "'Model'", "3", "1.E-5", f"#{axis}", "$")
    units = [step.add("IFCSIUNIT", "*", ".LENGTHUNIT.", "$", ".METRE."),
             step.add("IFCSIUNIT", "*", ".AREAUNIT.", "$", ".SQUARE_METRE."),
             step.add("IFCSIUNIT", "*", ".VOLUMEUNIT.", "$", ".CUBIC_METRE.")]
    unit_assign = step.add("IFCUNITASSIGNMENT",
                           "(" + ",".join(f"#{u}" for u in units) + ")")
    project = step.add("IFCPROJECT", _s(guid()), "$", _s(project_name),
                       "$", "$", "$", "$", f"(#{context})", f"#{unit_assign}")
    placement = step.add("IFCLOCALPLACEMENT", "$", f"#{axis}")
    site = step.add("IFCSITE", _s(guid()), "$", "'Site'", "$", "$",
                    f"#{placement}", "$", "$", ".ELEMENT.", "$", "$", "$",
                    "$", "$")
    building = step.add("IFCBUILDING", _s(guid()), "$", "'Building'", "$",
                        "$", f"#{placement}", "$", "$", ".ELEMENT.",
                        "$", "$", "$")
    storey = step.add("IFCBUILDINGSTOREY", _s(guid()), "$", "'Storey'", "$",
                      "$", f"#{placement}", "$", "$", ".ELEMENT.", "0.")
    for parent, child in ((project, site), (site, building),
                          (building, storey)):
        step.add("IFCRELAGGREGATES", _s(guid()), "$", "$", "$",
                 f"#{parent}", f"(#{child})")

    elements: list = []           # every element id, for the spatial relation
    pairs: list = []              # (group, element id), for the fill relations
    openings: dict = {}           # our opening id → the opening element
    for obj in objects:
        element, made = _element(step, table, scene, obj, context, placement,
                                 class_quantities)
        if element is None:
            continue
        elements.append(element)
        if obj.get("group") is not None:
            pairs.append((obj["group"], element))
        openings.update(made)

    if not elements:
        raise ValueError("No tagged BIM objects to export")
    step.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", _s(guid()), "$", "$", "$",
             "(" + ",".join(f"#{e}" for e in elements) + ")", f"#{storey}")
    _fill_relations(step, pairs, openings)

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((''),'2;1');\n"
        f"FILE_NAME('{Path(path).name.replace(chr(39), chr(39) * 2)}',"
        f"'{stamp}',('IngeTrazo'),('IngeTrazo'),'ingetrazo ifc_editor',"
        f"'{schema}','');\n"
        f"FILE_SCHEMA(('{schema}'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    Path(path).write_text(header + "\n".join(step.lines) + "\n" + footer,
                          encoding="ascii")
    return len(elements)


def _element(step: _Step, table, scene, obj, context, placement, quantities):
    """One tagged object, its property sets, and any openings it hosts."""
    faces = obj.get("faces")
    group = obj.get("group")
    if faces is None and group is not None:
        faces = list(group.mesh.faces)
    if not faces:
        return None, {}

    entity = None
    if group is not None:
        entity = group
    elif faces:
        entity = faces[0]
    data = store.record(scene, entity) if entity is not None else None
    if data is None:
        return None, {}

    ifc_class = data["class"] if table.has_entity(data["class"]) \
        else "IfcBuildingElementProxy"
    # The core tag's name is the source of truth for Name — it is what the BIM
    # panel, the take-off and the core's own export read.
    values = dict(data["fields"])
    values.setdefault("Name", data.get("name") or ifc_class)
    qset_name, entries, (metrado, unit) = quantities(data["class"], faces)
    _decorate(values, data["class"], entries)

    representation = brep(step, [(f.loop, f.hole_loops) for f in faces],
                          context)
    shape = step.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$",
                     f"(#{representation})")
    element = step.add(ifc_class, *_attributes(table, ifc_class, values,
                                               placement, shape))
    _psets(step, table, element, data, entries, qset_name)

    made: dict = {}
    wall = _wall_data(group) if group is not None else None
    if wall is not None:
        made = _voids(step, table, element, wall, context, placement)
    return element, made


def _decorate(values: dict, ifc_class: str, entries) -> None:
    """Values IFC wants that the geometry can measure, where it has them.

    A door carries its leaf size as OverallHeight/OverallWidth and a window the
    same; the schema says those attributes exist, and the quantities measure
    them. Anything the user typed wins.
    """
    if ifc_class not in ("IfcDoor", "IfcWindow", "IfcDoorStandardCase"):
        return
    dims = {name: value for kind, name, value in entries if kind == "length"}
    values.setdefault("OverallHeight", dims.get("Height"))
    values.setdefault("OverallWidth", dims.get("Width"))


def _attributes(table, ifc_class: str, values: dict, placement: int,
                shape: int) -> list:
    """The class's attributes, in the schema's own order — nothing hardcoded.

    ``ObjectPlacement`` and ``Representation`` are the geometry's, ``OwnerHistory``
    is left empty as the core does, and everything else is the user's value in
    the type the schema declares.
    """
    out = []
    for attribute in table.attributes(ifc_class):
        name = attribute["name"]
        if name == "GlobalId":
            out.append(_s(values.get("GlobalId") or guid()))
        elif name == "OwnerHistory":
            out.append("$")
        elif name == "ObjectPlacement":
            out.append(f"#{placement}")
        elif name == "Representation":
            out.append(f"#{shape}")
        else:
            kind = table.resolve_kind(attribute["type"])
            value = values.get(name)
            if kind == "enum" and value is not None:
                # Only a legal literal of *that* enumeration may be written. A
                # value from another enum — SINGLEPANEL is a window's
                # PartitioningType, not its PredefinedType — would be written as
                # an illegal STEP enumeration and read back as nothing at all.
                allowed = attribute.get("enum") or []
                if allowed and str(value).strip().upper() not in \
                        [option.upper() for option in allowed]:
                    value = None
            out.append(literal(kind, value))
    return out


def _psets(step: _Step, table, element: int, data: dict, entries,
           qset_name: str) -> None:
    """The user's property sets, and the class's standard quantities."""
    for name, values in (data.get("psets") or {}).items():
        declared = {p["name"]: p for p in
                    (table.pset(name) or {}).get("properties", [])}
        types = (data.get("pset_types") or {}).get(name) or {}
        props = []
        for prop_name, value in values.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            value_type = (declared.get(prop_name) or {}).get("value_type") \
                or types.get(prop_name) or "IfcLabel"
            kind = table.resolve_kind(value_type)
            props.append(step.add(
                "IFCPROPERTYSINGLEVALUE", _s(prop_name), "$",
                f"{_nominal(value_type)}({literal(kind, value)})", "$"))
        if not props:
            continue
        pset = step.add("IFCPROPERTYSET", _s(guid()), "$", _s(name), "$",
                        "(" + ",".join(f"#{p}" for p in props) + ")")
        step.add("IFCRELDEFINESBYPROPERTIES", _s(guid()), "$", "$", "$",
                 f"(#{element})", f"#{pset}")

    _Q = {"area": "IFCQUANTITYAREA", "volume": "IFCQUANTITYVOLUME",
          "length": "IFCQUANTITYLENGTH", "weight": "IFCQUANTITYWEIGHT"}
    quantities = [step.add(_Q[kind], _s(name), "$", "$", _f(value), "$")
                  for kind, name, value in entries if kind in _Q]
    if quantities:
        qset = step.add("IFCELEMENTQUANTITY", _s(guid()), "$",
                        _s(qset_name), "$", "$",
                        "(" + ",".join(f"#{q}" for q in quantities) + ")")
        step.add("IFCRELDEFINESBYPROPERTIES", _s(guid()), "$", "$", "$",
                 f"(#{element})", f"#{qset}")


def _nominal(value_type: str) -> str:
    """The IFC entity naming a property's value type."""
    name = (value_type or "IfcLabel").strip()
    if not name.lower().startswith("ifc"):
        return "IFCLABEL"
    return name.upper()


def _voids(step: _Step, table, wall_element: int, wall: dict, context: int,
           placement: int) -> dict:
    """A wall's openings: an IfcOpeningElement each, voiding the wall.

    This is how IFC describes a hole — the wall is not a mesh with a gap, it is
    an element with a related opening — and it is what makes the wall read as
    whole in any IFC viewer that looks for one.
    """
    made: dict = {}
    for opening in wall.get("openings") or ():
        faces = opening_faces(wall, opening)
        if not faces:
            continue
        representation = brep(step, faces, context)
        shape = step.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$",
                         f"(#{representation})")
        element = step.add("IFCOPENINGELEMENT", _s(guid()), "$", "$", "$", "$",
                           f"#{placement}", f"#{shape}", "$", ".OPENING.")
        step.add("IFCRELVOIDSELEMENT", _s(guid()), "$", "$", "$",
                 f"#{wall_element}", f"#{element}")
        made[opening.get("id")] = element
    return made


def _fill_relations(step: _Step, pairs, openings: dict) -> None:
    """Where a door or window stands in an opening: ``IfcRelFillsElement``."""
    for group, element in pairs:
        ext = getattr(group, "ext", None) or {}
        data = ext.get(OPENINGS_KEY) if isinstance(ext, dict) else None
        host = (data or {}).get("host") or {}
        opening = openings.get(host.get("opening"))
        if opening is None:
            continue
        step.add("IFCRELFILLSELEMENT", _s(guid()), "$", "$", "$",
                 f"#{opening}", f"#{element}")
