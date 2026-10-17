# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The IFC schema tables, and the questions the editor asks of them.

Pure Python, no Qt: everything here is testable without the application.

The tables in ``data/`` are generated offline from buildingSMART's own EXPRESS
schemas and property-set definitions by ``dev/schema/`` — see
``dev/schema/README.md``. IFC is a trademark of, and the schemas are copyright,
buildingSMART International Limited; the tables carry the attribution.

Two schemas are shipped because the user's own project files are IFC2X3, and
the two differ in ways that matter here: IFC2X3 keeps ``PredefinedType`` on the
*Type* entities, so most IFC2X3 occurrences have none at all, and its property
sets name their applicable entities differently.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

#: The schemas we can edit against, newest first.
SCHEMAS = ("IFC4", "IFC2X3")

#: Attributes that describe where an object *is* or what it *looks* like rather
#: than what it *is*. They are derived from the geometry IngeTrazo already
#: holds, so the editor shows them but never lets them be typed over — writing
#: them here would contradict the model or be silently ignored downstream.
DERIVED_ATTRIBUTES = frozenset({
    "OwnerHistory", "ObjectPlacement", "Representation",
})

#: Simple types that are a number rather than a string, by EXPRESS kind.
_NUMERIC_KINDS = frozenset({"integer", "real", "number"})

_cache: dict[str, "Table"] = {}


class Table:
    """One schema's entities, defined types and property sets."""

    def __init__(self, data: dict) -> None:
        self._data = data
        self.schema: str = data.get("schema", "")
        self.entities: dict = data.get("entities", {})
        self.types: dict = data.get("types", {})
        self.psets: dict = data.get("psets", {})
        self.attribution: str = data.get("attribution", "")
        self._class_names: list[str] | None = None
        self._product_names: list[str] | None = None

    # ---- entities ----------------------------------------------------------
    def entity(self, name: str) -> dict | None:
        return self.entities.get(name)

    def has_entity(self, name: str) -> bool:
        return name in self.entities

    def attributes(self, name: str) -> list[dict]:
        """``name``'s explicit attributes, inherited first, own last — the
        order IFC writes them in."""
        entity = self.entities.get(name)
        return list(entity.get("attributes", ())) if entity else []

    def is_subtype_of(self, name: str, ancestor: str) -> bool:
        """True when ``name`` is ``ancestor`` or a subtype of it."""
        seen: set[str] = set()
        current: str | None = name
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            entity = self.entities.get(current)
            if entity is None:
                return False
            current = entity.get("supertype")
        return False

    def class_names(self) -> list[str]:
        """Every entity, for a class picker. Concrete ones only: an abstract
        entity is never the class of a real object."""
        if self._class_names is None:
            self._class_names = sorted(
                name for name, entity in self.entities.items()
                if not entity.get("abstract"))
        return self._class_names

    def product_names(self) -> list[str]:
        """The entities that can be tagged onto geometry: subtypes of
        ``IfcProduct``. These are what the class picker offers first, because
        the rest (relationships, representations, types) are not things a face
        becomes."""
        if self._product_names is None:
            self._product_names = [
                name for name in self.class_names()
                if self.is_subtype_of(name, "IfcProduct")]
        return self._product_names

    def predefined_types(self, name: str) -> list[str]:
        entity = self.entities.get(name)
        if not entity:
            return []
        return list(entity.get("predefined_type", {}).get("values", ()))

    def predefined_attribute(self, name: str) -> str | None:
        """The name of the attribute holding the predefined type, if any.

        Normally ``PredefinedType``; ``IfcSpace`` is the exception that bites,
        carrying ``CompositionType`` in IFC2X3 and no predefined type at all.
        """
        entity = self.entities.get(name)
        if not entity:
            return None
        return entity.get("predefined_type", {}).get("attribute")

    # ---- defined types -----------------------------------------------------
    def type_info(self, name: str) -> dict | None:
        return self.types.get(name)

    def resolve_kind(self, type_name: str) -> str:
        """What kind of value a declared type holds, for choosing an editor.

        Returns one of ``boolean``, ``integer``, ``real``, ``number``,
        ``string``, ``enum``, ``select``, ``aggregate``, ``entity``,
        ``unknown``. An alias is followed to whatever it points at, so
        ``IfcLengthMeasure`` is a ``real`` and ``IfcLabel`` a ``string``.
        """
        seen: set[str] = set()
        current = (type_name or "").strip()
        while current and current not in seen:
            seen.add(current)
            if current in self.entities:
                return "entity"
            info = self.types.get(current)
            if info is None:
                upper = current.upper()
                if upper == "BOOLEAN":
                    return "boolean"
                if upper in ("INTEGER", "REAL", "NUMBER"):
                    return upper.lower()
                if upper == "STRING":
                    return "string"
                return "unknown"
            kind = info.get("kind", "")
            if kind == "enum":
                return "enum"
            if kind == "select":
                return "select"
            if kind == "aggregate":
                return "aggregate"
            if kind in _NUMERIC_KINDS:
                return kind
            if kind == "string":
                return "string"
            if kind == "boolean":
                return "boolean"
            if kind == "alias":
                current = str(info.get("of", "")).strip()
                continue
            return kind or "unknown"
        return "unknown"

    def enum_values(self, type_name: str) -> list[str]:
        """Enumeration literals behind a type, following an alias if needed."""
        seen: set[str] = set()
        current = (type_name or "").strip()
        while current and current not in seen:
            seen.add(current)
            info = self.types.get(current)
            if info is None:
                return []
            if info.get("kind") == "enum":
                return list(info.get("values", ()))
            if info.get("kind") == "alias":
                current = str(info.get("of", "")).strip()
                continue
            return []
        return []

    # ---- property sets -----------------------------------------------------
    def psets_for(self, ifc_class: str,
                  predefined_type: str | None = None) -> list[tuple[str, dict]]:
        """The property and quantity sets that apply to ``ifc_class``.

        A set applies when its applicable entity is the class or one of its
        supertypes — buildingSMART names the *most general* entity a set is for,
        and expects a subtype to inherit it. A suffix such as
        ``IfcCovering/FLOORING`` narrows it to coverings whose predefined type
        is FLOORING.
        """
        out: list[tuple[str, dict]] = []
        for name in sorted(self.psets):
            entry = self.psets[name]
            if self._applies(entry, ifc_class, predefined_type):
                out.append((name, entry))
        return out

    def _applies(self, entry: dict, ifc_class: str,
                 predefined_type: str | None) -> bool:
        for target in entry.get("applicable", ()):
            entity, _, wanted = target.partition("/")
            if not self.is_subtype_of(ifc_class, entity):
                continue
            if wanted and (predefined_type or "").upper() != wanted.upper():
                continue
            return True
        return False

    def pset(self, name: str) -> dict | None:
        return self.psets.get(name)


def load(schema: str) -> Table:
    """The table for ``schema`` (``IFC4`` / ``IFC2X3``), read once and kept.

    Reading ~1.3 MB of JSON takes long enough to notice at startup and the
    editor needs one schema at a time, so this is lazy and cached rather than
    done when the plugin loads.
    """
    wanted = (schema or "IFC4").upper().replace("IFC2X3_TC1", "IFC2X3")
    if wanted not in SCHEMAS:
        wanted = "IFC4"
    table = _cache.get(wanted)
    if table is not None:
        return table
    path = DATA_DIR / f"{wanted.lower()}.json.gz"
    if not path.is_file():
        raise FileNotFoundError(f"the IFC schema table is missing: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    table = Table(data)
    _cache[wanted] = table
    return table


def available(schema: str) -> bool:
    """Whether the table for ``schema`` is present, without reading it."""
    wanted = (schema or "IFC4").upper()
    return (DATA_DIR / f"{wanted.lower()}.json.gz").is_file()
