#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Check the schema tables the extension actually ships.

``generate.py --verify`` checks the tables it has just built from the sources
in ``dev/schema/src/``. This checks the committed artefacts, so it runs on a
fresh clone where those sources were never fetched — which is the state CI and
every other machine will be in.

The strongest check here is the last one: every type name mentioned by an
attribute has to resolve to an entity, a defined type, or a primitive of the
schema. A parser that mis-reads a declaration almost always leaves a name
behind that resolves to nothing.

Usage:  python3 dev/schema/test_tables.py        (exit 1 on failure)
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

TABLES = (Path(__file__).resolve().parent.parent.parent
          / "extensions" / "ifc_editor" / "data")

#: Words that appear inside an attribute's declared type without naming a type.
KEYWORDS = frozenset({
    "LIST", "SET", "ARRAY", "BAG", "OF", "OPTIONAL", "UNIQUE", "STRING",
    "REAL", "INTEGER", "NUMBER", "BOOLEAN", "LOGICAL", "BINARY",
})

#: What each schema must contain, as (entity count, property-set count).
EXPECTED_COUNTS = {"ifc4": (776, 513), "ifc2x3": (653, 317)}

#: The primitives an attribute type may fall back to.
PRIMITIVES = frozenset({"REAL", "INTEGER", "NUMBER", "BOOLEAN", "LOGICAL",
                        "BINARY", "STRING"})

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def load(stem: str) -> dict:
    path = TABLES / f"{stem}.json.gz"
    if not path.is_file():
        failures.append(f"{path.name} is missing — run dev/schema/generate.py")
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def attribute_names(table: dict, entity: str) -> list[str]:
    return [a["name"] for a in table["entities"].get(entity, {})
            .get("attributes", [])]


def test_counts(stem: str, table: dict) -> None:
    entities, psets = len(table.get("entities", {})), len(table.get("psets", {}))
    want_entities, want_psets = EXPECTED_COUNTS[stem]
    check(entities == want_entities,
          f"{stem}: {entities} entities, expected {want_entities}")
    check(psets == want_psets,
          f"{stem}: {psets} property sets, expected {want_psets}")
    check(bool(table.get("attribution")),
          f"{stem}: no attribution recorded")
    check(bool(table.get("sources")), f"{stem}: no sources recorded")


def test_ifc4(table: dict) -> None:
    check(attribute_names(table, "IfcWall") == [
        "GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
        "ObjectPlacement", "Representation", "Tag", "PredefinedType"],
        f"IFC4 IfcWall attributes: {attribute_names(table, 'IfcWall')}")

    values = table["entities"]["IfcWall"].get("predefined_type", {}) \
        .get("values", [])
    check("STANDARD" in values and "MOVABLE" in values,
          f"IFC4 IfcWall PredefinedType values look wrong: {values[:6]}")

    door = attribute_names(table, "IfcDoor")
    check(door[8:10] == ["OverallHeight", "OverallWidth"],
          f"IFC4 IfcDoor should carry OverallHeight/OverallWidth at 9-10, "
          f"got {door[8:10]}")

    # The declaring entity has to be recorded, or a form cannot group its
    # fields by IfcRoot / IfcObject / IfcElement / the entity's own.
    global_id = table["entities"]["IfcWall"]["attributes"][0]
    check(global_id.get("inherited_from") == "IfcRoot",
          f"GlobalId should be marked as declared on IfcRoot, got "
          f"{global_id.get('inherited_from')!r}")
    predefined = next(a for a in table["entities"]["IfcWall"]["attributes"]
                      if a["name"] == "PredefinedType")
    check("inherited_from" not in predefined,
          "an entity's own attribute must not be marked as inherited")

    wall = table["psets"].get("Pset_WallCommon", {})
    check(wall.get("applicable") == ["IfcWall"],
          f"IFC4 Pset_WallCommon applies to {wall.get('applicable')!r}")
    names = [p["name"] for p in wall.get("properties", [])]
    for wanted in ("Reference", "IsExternal", "LoadBearing", "FireRating"):
        check(wanted in names, f"IFC4 Pset_WallCommon is missing {wanted}")
    external = next((p for p in wall.get("properties", [])
                      if p["name"] == "IsExternal"), {})
    check(external.get("value_type") == "IfcBoolean",
          f"IsExternal should be IfcBoolean, is {external.get('value_type')!r}")

    # A predefined-type filter, which must survive parsing.
    covering = table["psets"].get("Pset_CoveringFlooring", {}) \
        .get("applicable", [])
    check("IfcCovering/FLOORING" in covering,
          f"Pset_CoveringFlooring should keep the /FLOORING filter: {covering}")

    check(any(pset.get("kind") == "qto" for pset in table["psets"].values()),
          "IFC4: no quantity sets found")
    check(sum(1 for pset in table["psets"].values()
              if pset.get("kind") == "qto") >= 40,
          "IFC4: suspiciously few quantity sets")


def test_ifc2x3(table: dict) -> None:
    check("PredefinedType" not in attribute_names(table, "IfcWall"),
          "IFC2X3 IfcWall should not carry PredefinedType")
    check("IfcWallStandardCase" in table["entities"],
          "IFC2X3 should define IfcWallStandardCase")
    wall = table["psets"].get("Pset_WallCommon", {})
    check(wall.get("applicable") == ["IfcWall", "IfcWallStandardCase"],
          f"IFC2X3 Pset_WallCommon applies to {wall.get('applicable')!r}")
    # The schema-domain prefix form, which only IFC2X3 uses.
    motor = table["psets"].get("Pset_ElectricMotorTypeCommon", {}) \
        .get("applicable", [])
    check("IfcElectricMotorType" in motor,
          f"the domain prefix was not stripped: {motor!r}")
    check(all(not target.startswith("IFC") for target in motor),
          f"a domain name leaked into an applicable list: {motor!r}")


def test_integrity(stem: str, table: dict) -> None:
    """Referential integrity: entities, inheritance and every type name."""
    entities = table.get("entities", {})
    psets = table.get("psets", {})
    types = table.get("types", {})

    if not types:
        failures.append(f"{stem}: the table has no defined types, so a field's "
                        f"declared type cannot be resolved")
        return

    # A type name is legitimate when it is an entity, a defined type, or a
    # primitive of the schema.
    named = set(entities) | set(types)
    for entity in entities.values():
        for attribute in entity.get("attributes", []):
            named.add(attribute["type"])
            named.update(attribute.get("enum", ()))
            named.update(attribute.get("select", ()))

    for entity_name, entity in entities.items():
        supertype = entity.get("supertype")
        if supertype is not None:
            check(supertype in entities,
                  f"{stem}: {entity_name} inherits from unknown {supertype!r}")
        for attribute in entity.get("attributes", []):
            origin = attribute.get("inherited_from")
            if origin is not None:
                check(origin in entities,
                      f"{stem}: {entity_name}.{attribute['name']} claims to "
                      f"come from unknown {origin!r}")
                check(origin != entity_name,
                      f"{stem}: {entity_name}.{attribute['name']} is marked "
                      f"as inherited from itself")
            for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", attribute["type"]):
                if word.upper() in KEYWORDS:
                    continue
                check(word in entities or word in named,
                      f"{stem}: {entity_name}.{attribute['name']} has type "
                      f"{attribute['type']!r}, whose {word!r} resolves to "
                      f"nothing")

    for pset_name, pset in psets.items():
        applicable = pset.get("applicable", [])
        if not applicable:
            failures.append(f"{stem}: {pset_name} applies to nothing")
        for target in applicable:
            entity = target.split("/")[0]
            check(entity in entities,
                  f"{stem}: {pset_name} applies to unknown entity {entity!r}")
        for prop in pset.get("properties", []):
            value_type = prop.get("value_type")
            if value_type is None:
                continue
            # `PEnum_*` is the name of the enumeration a P_ENUMERATEDVALUE
            # property draws its values from. It is not an Ifc type — the
            # values themselves are in the entry's `enum`.
            if value_type.startswith("PEnum_"):
                check(bool(prop.get("enum")),
                      f"{stem}: {pset_name}.{prop['name']} names "
                      f"{value_type!r} but carries no values")
                continue
            check(value_type in entities or value_type in named
                  or value_type.upper() in PRIMITIVES,
                  f"{stem}: {pset_name}.{prop['name']} has value type "
                  f"{value_type!r}, which resolves to nothing")


def main() -> int:
    for stem in ("ifc4", "ifc2x3"):
        table = load(stem)
        if not table:
            continue
        test_counts(stem, table)
        (test_ifc4 if stem == "ifc4" else test_ifc2x3)(table)
        test_integrity(stem, table)

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} problem(s) in the schema tables.")
        return 1
    print("schema tables: ok (2 schemas, counts, shapes and referential "
          "integrity)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
