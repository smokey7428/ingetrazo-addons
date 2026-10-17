# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""A reader for the EXPRESS schema files buildingSMART publishes (``.exp``).

We need three things out of a schema, and nothing else:

* every **entity**, with the ordered explicit attributes it has — its own
  first, then its supertype's, up to the root — each with its declared type and
  whether it is OPTIONAL;
* the **enumeration values** behind a type (``IfcWallTypeEnum``…), so a
  ``PredefinedType`` can be offered as a list and not as free text;
* the **inheritance graph**, to know which entity is a subtype of which.

Functions, rules, derived and inverse attributes and WHERE clauses are
recognised only so they can be skipped.

The EXPRESS grammar is far bigger than this, but an IFC ``.exp`` uses a small,
regular corner of it, and this reader stays inside that corner on purpose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"\(\*.*?\*\)", re.DOTALL)

#: Keywords that end the explicit-attribute section of an entity.
_SECTION_KEYWORDS = ("INVERSE", "DERIVE", "WHERE", "UNIQUE")

#: The section keywords that may follow ``SUBTYPE OF (…)``/``SUPERTYPE OF (…)``.
_ATTR_SECTIONS = frozenset(_SECTION_KEYWORDS)


@dataclass
class Attribute:
    """One explicit attribute of an entity."""

    name: str
    type: str
    optional: bool = False
    #: The entity this attribute was declared on, when inherited.
    inherited_from: str | None = None

    def as_dict(self) -> dict:
        out = {"name": self.name, "type": self.type}
        if self.optional:
            out["optional"] = True
        if self.inherited_from:
            out["inherited_from"] = self.inherited_from
        return out


@dataclass
class Entity:
    name: str
    abstract: bool = False
    supertype: str | None = None
    own_attributes: list[Attribute] = field(default_factory=list)
    subtypes: list[str] = field(default_factory=list)


@dataclass
class DefinedType:
    """A ``TYPE`` declaration: an enumeration, a select, or a simple type."""

    name: str
    kind: str                                  # enum | select | string | …
    values: list[str] = field(default_factory=list)   # enum values, select members
    of_type: str | None = None                 # element type of a list/set, or alias target
    size: int | None = None                    # character count of a STRING


def _split_top_level(text: str, sep: str = ";") -> list[str]:
    """Split on ``sep`` outside parentheses and brackets."""
    parts, depth, current = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _type_kind(body: str) -> tuple[str, list[str], str | None, int | None]:
    """Classify a ``TYPE`` body → ``(kind, values, of_type, size)``."""
    flat = " ".join(body.split())
    if flat.upper().startswith("ENUMERATION"):
        inner = flat[flat.find("(") + 1:flat.rfind(")")]
        return "enum", [v.strip() for v in inner.split(",") if v.strip()], None, None
    if flat.upper().startswith("SELECT"):
        inner = flat[flat.find("(") + 1:flat.rfind(")")]
        return "select", [v.strip() for v in inner.split(",") if v.strip()], None, None
    if flat.upper().startswith(("LIST", "SET", "ARRAY", "BAG")):
        match = re.search(r"\bOF\s+(.+)$", flat, re.IGNORECASE)
        return "aggregate", [], match.group(1).strip() if match else None, None
    if flat.upper().startswith("STRING"):
        size = re.search(r"\((\d+)\)", flat)
        return "string", [], None, int(size.group(1)) if size else None
    head = re.split(r"[;\s(]", flat, maxsplit=1)[0].upper()
    for simple in ("REAL", "INTEGER", "NUMBER", "BOOLEAN", "LOGICAL", "BINARY"):
        if head == simple:
            return simple.lower(), [], None, None
    # An alias of another defined type or entity: `TYPE IfcLabel = STRING(255);`
    return "alias", [], flat.split(";")[0].strip(), None


class Schema:
    """An EXPRESS schema, read into entities and defined types."""

    def __init__(self, text: str, name: str = "") -> None:
        self.name = name
        self.entities: dict[str, Entity] = {}
        self.types: dict[str, DefinedType] = {}
        self._parse(_COMMENT.sub(" ", text))

    # ---- reading -----------------------------------------------------------
    def _parse(self, text: str) -> None:
        for match in re.finditer(r"\bENTITY\s+(\w+)\b(.*?)\bEND_ENTITY\s*;",
                                 text, re.DOTALL):
            entity = self._parse_entity(match.group(1), match.group(2))
            self.entities[entity.name] = entity
        for match in re.finditer(r"\bTYPE\s+(\w+)\s*=\s*(.*?)\bEND_TYPE\s*;",
                                 text, re.DOTALL):
            kind, values, of_type, size = _type_kind(match.group(2))
            self.types[match.group(1)] = DefinedType(match.group(1), kind,
                                                     values, of_type, size)
        for entity in self.entities.values():
            if entity.supertype and entity.supertype in self.entities:
                self.entities[entity.supertype].subtypes.append(entity.name)

    def _parse_entity(self, name: str, body: str) -> Entity:
        entity = Entity(name)
        if re.search(r"\bABSTRACT\s+SUPERTYPE\b|\bABSTRACT\b", body):
            entity.abstract = True
        sub = re.search(r"\bSUBTYPE\s+OF\s*\(\s*(\w+)\s*\)", body)
        if sub:
            entity.supertype = sub.group(1)

        # The explicit attributes run from after the SUBTYPE line to the first
        # section keyword. Splitting on ';' is safe: an attribute's type never
        # contains one (aggregate bounds use brackets).
        tail = re.split(r"\b(" + "|".join(_ATTR_SECTIONS) + r")\b", body,
                        maxsplit=1)[0]
        for chunk in _split_top_level(tail):
            chunk = " ".join(chunk.split())
            if not chunk or chunk.upper().startswith(("SUPERTYPE", "SUBTYPE")):
                continue
            match = re.match(r"^(\w+)\s*:\s*(OPTIONAL\s+)?(.+)$", chunk,
                             re.IGNORECASE)
            if match:
                entity.own_attributes.append(Attribute(
                    match.group(1), match.group(3).strip(),
                    bool(match.group(2))))
        return entity

    # ---- queries -----------------------------------------------------------
    def all_attributes(self, name: str) -> list[Attribute]:
        """``name``'s explicit attributes in declaration order: inherited
        first, then its own — the order IFC writes them in a STEP file.

        Each attribute records the entity it was *declared on* in
        ``inherited_from``, this entity included. A caller describing
        ``IfcWall`` can therefore tell GlobalId (from IfcRoot) apart from
        PredefinedType (its own), and group a form by declaring entity.
        """
        entity = self.entities.get(name)
        if entity is None:
            return []
        out: list[Attribute] = []
        if entity.supertype:
            out.extend(self.all_attributes(entity.supertype))
        out.extend(Attribute(attr.name, attr.type, attr.optional, name)
                   for attr in entity.own_attributes)
        return out

    def is_subtype_of(self, name: str, ancestor: str) -> bool:
        """True when ``name`` is ``ancestor`` or a (transitive) subtype."""
        seen: set[str] = set()
        current: str | None = name
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            entity = self.entities.get(current)
            current = entity.supertype if entity else None
        return False

    def enum_values(self, type_name: str) -> list[str]:
        defined = self.types.get(type_name)
        if defined is not None and defined.kind == "enum":
            return list(defined.values)
        if defined is not None and defined.kind == "alias" and defined.of_type:
            return self.enum_values(defined.of_type)
        return []

    def select_members(self, type_name: str) -> list[str]:
        defined = self.types.get(type_name)
        if defined is not None and defined.kind == "select":
            return list(defined.values)
        return []
