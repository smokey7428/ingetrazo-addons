#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Build the IFC schema tables the ifc_editor extension ships.

Input   dev/schema/src/  (fetch with ./dev/schema/fetch.sh — not committed)
Output  extensions/ifc_editor/data/ifc4.json, ifc2x3.json

Why generate instead of reading the schema at runtime: an IngeTrazo extension
must be self-contained. There is no dependency mechanism for extensions
(``plugin.toml`` is upstream roadmap, unimplemented) and the app bundle ships
no IFC library, so a runtime schema lookup would mean shipping the whole
schemas — or asking every user to pip install. Compact tables generated once,
offline, solve that.

Provenance is recorded in the output: these tables are derived from
buildingSMART's schemas and property-set definitions, which their licence
permits for software development **with full attribution**. Keep the
attribution in the extension's header and in dev/schema/README.md.

Usage:
    python3 dev/schema/generate.py              # write the tables
    python3 dev/schema/generate.py --verify     # check them against known facts
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import express  # noqa: E402
import spf  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
OUT = HERE.parent.parent / "extensions" / "ifc_editor" / "data"

#: One entry per schema we ship: the EXPRESS file, the property-set file, and
#: the name the tables answer to.
SCHEMAS = (
    {
        "name": "IFC4",
        "express": "IFC4.exp",
        "psets": "Pset_IFC4_ADD2.ifc",
    },
    {
        "name": "IFC2X3",
        "express": "IFC2X3_TC1.exp",
        "psets": "Pset_IFC2X3.ifc",
    },
)

SOURCES = {
    "IFC4.exp":
        "https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/"
        "EXPRESS/IFC4.exp",
    "IFC2X3_TC1.exp":
        "https://standards.buildingsmart.org/IFC/RELEASE/IFC2x3/TC1/"
        "EXPRESS/IFC2X3_TC1.exp",
    "Pset_IFC4_ADD2.ifc":
        "https://github.com/IfcOpenShell/IfcOpenShell, "
        "src/ifcopenshell-python/ifcopenshell/util/schema/",
    "Pset_IFC2X3.ifc":
        "https://github.com/IfcOpenShell/IfcOpenShell, "
        "src/ifcopenshell-python/ifcopenshell/util/schema/",
}

ATTRIBUTION = (
    "Derived from the EXPRESS schemas and property-set definitions published "
    "by buildingSMART International Limited; used with attribution. "
    "IFC is a trademark of buildingSMART International Limited."
)


# ---- entities ---------------------------------------------------------------
def _attribute_entry(schema: express.Schema, attr: express.Attribute,
                      owner: str) -> dict:
    """One attribute as the extension wants to see it.

    ``owner`` is the entity being described: an attribute declared on it needs
    no ``inherited_from``, one that came down the chain does.
    """
    entry: dict = {"name": attr.name, "type": attr.type}
    if attr.optional:
        entry["optional"] = True
    if attr.inherited_from and attr.inherited_from != owner:
        entry["inherited_from"] = attr.inherited_from

    enum = schema.enum_values(attr.type)
    if enum:
        entry["enum"] = enum
    else:
        # A SELECT is an open set of alternatives — worth listing, so a field
        # can be edited with its real choices instead of as free text.
        members = schema.select_members(attr.type)
        if members:
            entry["select"] = members
    return entry


def build_entities(schema: express.Schema) -> dict:
    out: dict = {}
    for name, entity in sorted(schema.entities.items()):
        entry: dict = {}
        if entity.supertype:
            entry["supertype"] = entity.supertype
        if entity.abstract:
            entry["abstract"] = True
        attributes = [_attribute_entry(schema, a, name)
                      for a in schema.all_attributes(name)]
        entry["attributes"] = attributes

        predefined = next((a for a in attributes
                           if a["name"] == "PredefinedType"), None)
        if predefined is not None and "enum" in predefined:
            entry["predefined_type"] = {
                "attribute": "PredefinedType",
                "type": predefined["type"],
                "values": predefined["enum"],
            }
        out[name] = entry
    return out


# ---- property sets ----------------------------------------------------------
def _enumerators(instances: dict, ref) -> list[str]:
    """The literal values behind an ``IFCPROPERTYENUMERATION`` reference."""
    if not isinstance(ref, spf.Ref):
        return []
    instance = instances.get(ref.id)
    if instance is None:
        return []
    listing = instance.get(1)
    if not isinstance(listing, tuple):
        return []
    return [str(value) for value in listing if isinstance(value, str)]


def _applicable_entities(schema: express.Schema, raw, warnings: list) -> list[str]:
    """Parse a pset's ``ApplicableEntity`` into ``"Entity"`` / ``"Entity/TYPE"``.

    The field is a comma-separated list, and a token is not always a bare
    entity name. Two variants occur in the published files:

    * ``IfcCovering/FLOORING`` — the entity, then a PredefinedType the object
      must have for the set to apply;
    * ``IFCELECTRICALDOMAIN/IfcElectricMotorType`` — a schema *domain* prefix
      (IFC2X3 only) before the entity.

    An entity name always starts with ``Ifc``, so the entity is the first
    token part that does: a trailing part is a PredefinedType filter, a
    leading one is a domain and is dropped.
    """
    if not isinstance(raw, str):
        return []
    out: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        parts = [p.strip() for p in token.split("/") if p.strip()]
        index = next((i for i, p in enumerate(parts) if p.startswith("Ifc")),
                      None)
        if index is None:
            warnings.append(f"{token!r}: no entity in this token")
            continue
        entity = parts[index]
        if entity not in schema.entities:
            warnings.append(f"{entity!r} is not an entity of "
                            f"{schema.name}")
        after = parts[index + 1:]
        out.append(f"{entity}/{after[0]}" if after else entity)
    return out


def build_psets(instances: dict, schema: express.Schema,
                warnings: list) -> dict:
    """``IfcPropertySetTemplate`` + ``IfcSimplePropertyTemplate`` → sets."""
    templates: dict[int, spf.Instance] = {
        i: inst for i, inst in instances.items()
        if inst.type_name == "IFCSIMPLEPROPERTYTEMPLATE"
    }

    out: dict = {}
    for instance in instances.values():
        if instance.type_name != "IFCPROPERTYSETTEMPLATE":
            continue
        name = instance.get(2)
        if not isinstance(name, str):
            continue
        template_type = instance.get(4)
        template_type = str(template_type) if template_type is not None else ""
        entry: dict = {
            "template_type": template_type,
            "kind": ("qto" if template_type.upper().startswith("QTO")
                     else "pset"),
        }
        applicable = _applicable_entities(schema, instance.get(5), warnings)
        if applicable:
            entry["applicable"] = applicable

        properties = []
        for ref in instance.get(6) or ():
            if not isinstance(ref, spf.Ref):
                continue
            prop = templates.get(ref.id)
            if prop is None:
                continue
            prop_name = prop.get(2)
            if not isinstance(prop_name, str):
                continue
            item: dict = {"name": prop_name}
            # The IFC2X3 files carry stray spaces around some measure names
            # (' IfcElectricCurrentMeasure', 'IfcMaterial '), which would
            # never match an entity or a defined type.
            measure = prop.get(5)
            if isinstance(measure, str) and measure.strip():
                item["value_type"] = measure.strip()
            prop_type = prop.get(4)
            if prop_type is not None:
                item["property_type"] = str(prop_type).strip()
            values = _enumerators(instances, prop.get(7))
            if values:
                item["enum"] = values
            description = prop.get(3)
            if isinstance(description, str) and description:
                item["description"] = description
            properties.append(item)
        entry["properties"] = properties
        description = instance.get(3)
        if isinstance(description, str) and description:
            entry["description"] = description
        out[name] = entry
    return out


# ---- driver -----------------------------------------------------------------
def build_types(schema: express.Schema) -> dict:
    """Every defined type, so a field's declared type always resolves.

    An attribute's type is frequently a defined type rather than an entity —
    ``IfcPositiveInteger``, ``IfcMonetaryMeasure``, or a SELECT such as
    ``IfcShell``. Without this section those names lead nowhere, and an editor
    cannot tell a measure from a text field, nor offer a SELECT's alternatives.
    """
    out: dict = {}
    for name, defined in sorted(schema.types.items()):
        entry: dict = {"kind": defined.kind}
        if defined.values:
            entry["values"] = list(defined.values)
        if defined.of_type:
            entry["of"] = defined.of_type
        if defined.size is not None:
            entry["size"] = defined.size
        out[name] = entry
    return out


def build(spec: dict, warnings: list) -> dict:
    exp_path = SRC / spec["express"]
    pset_path = SRC / spec["psets"]
    schema = express.Schema(exp_path.read_text(encoding="utf-8",
                                               errors="replace"),
                             spec["name"])
    psets = spf.parse(pset_path.read_text(encoding="utf-8", errors="replace"))
    table = {
        "schema": spec["name"],
        "generated": date.today().isoformat(),
        "attribution": ATTRIBUTION,
        "sources": {name: SOURCES[name]
                    for name in (spec["express"], spec["psets"])},
        "entities": build_entities(schema),
        "types": build_types(schema),
        "psets": build_psets(psets, schema, warnings),
    }
    # Every entity a property set claims has to exist, or the runtime lookup
    # would silently offer a set that can never be filled in.
    for name, pset in table["psets"].items():
        for target in pset.get("applicable", ()):
            entity = target.split("/")[0]
            if entity not in table["entities"]:
                warnings.append(f"{name} applies to unknown {entity!r}")
    return table


def verify(table: dict) -> list[str]:
    """Known facts about IFC4/IFC2X3, checked against what we generated."""
    problems: list[str] = []
    entities, psets = table["entities"], table["psets"]

    def attributes(name):
        return [a["name"] for a in entities.get(name, {}).get("attributes", [])]

    def check(condition, message):
        if not condition:
            problems.append(message)

    check(len(entities) > 600,
          f"{table['schema']}: only {len(entities)} entities")

    # A truncated attribute type is how an entity body gets cut in half. The
    # section keywords are matched only at the start of a line, because ``UNIQUE``
    # is also a word inside an aggregate type — and while it was matched anywhere,
    # every entity that declared ``LIST [1:?] OF UNIQUE …`` lost everything after
    # it, which was the ``Tag`` on 231 type entities in the two schemas.
    for name, entry in entities.items():
        for attribute in entry.get("attributes", []):
            declared = attribute["type"].strip()
            check(not declared.upper().endswith(" OF"),
                  f"{table['schema']}: {name}.{attribute['name']} has a "
                  f"truncated type {declared!r}")

    # A type entity is an IfcTypeProduct, so it carries Tag before its own
    # attributes. Named here because a type object written without it is a file
    # a real consumer refuses.
    kinds = attributes("IfcWallType")
    check(kinds[-3:] == ["Tag", "ElementType", "PredefinedType"],
          f"IfcWallType should end Tag/ElementType/PredefinedType, "
          f"got {kinds[-3:]}")
    check(len(psets) > 250, f"{table['schema']}: only {len(psets)} psets")

    if table["schema"] == "IFC4":
        # IfcWall grew PredefinedType in IFC4; IFC2X3 kept it on the type.
        check(attributes("IfcWall") == [
            "GlobalId", "OwnerHistory", "Name", "Description", "ObjectType",
            "ObjectPlacement", "Representation", "Tag", "PredefinedType"],
            f"IfcWall attributes are {attributes('IfcWall')}")
        values = entities["IfcWall"].get("predefined_type", {}).get("values", [])
        check("STANDARD" in values and "MOVABLE" in values,
              f"IfcWall PredefinedType values look wrong: {values[:6]}")
        # Doors add their leaf dimensions before PredefinedType (attributes
        # 9-10 of 13), which schedules read.
        door = attributes("IfcDoor")
        check(door[8:10] == ["OverallHeight", "OverallWidth"],
              f"IfcDoor should carry OverallHeight/OverallWidth at 9-10, "
              f"got {door[8:10]}")
        check("PredefinedType" in door, "IfcDoor should carry PredefinedType")
        wall = psets.get("Pset_WallCommon", {})
        check(wall.get("applicable") == ["IfcWall"],
              f"Pset_WallCommon applies to {wall.get('applicable')!r}")
        names = [p["name"] for p in wall.get("properties", [])]
        for wanted in ("Reference", "IsExternal", "LoadBearing", "FireRating"):
            check(wanted in names, f"Pset_WallCommon is missing {wanted}")
        external = next((p for p in wall.get("properties", [])
                         if p["name"] == "IsExternal"), {})
        check(external.get("value_type") == "IfcBoolean",
              f"IsExternal should be IfcBoolean, is "
              f"{external.get('value_type')!r}")
        # The predefined-type filter form: Pset_CoveringFlooring is for
        # coverings whose PredefinedType is FLOORING, not for every covering.
        check("IfcCovering/FLOORING" in
              psets.get("Pset_CoveringFlooring", {}).get("applicable", []),
              "Pset_CoveringFlooring should carry the /FLOORING filter")
        check(any(p.get("kind") == "qto" for p in psets.values()),
              "no quantity sets found")
    else:
        check("PredefinedType" not in attributes("IfcWall"),
              "IFC2X3 IfcWall should not carry PredefinedType")
        check("IfcWallStandardCase" in entities,
              "IFC2X3 should define IfcWallStandardCase")
        wall = psets.get("Pset_WallCommon", {})
        check(wall.get("applicable") == ["IfcWall", "IfcWallStandardCase"],
              f"Pset_WallCommon applies to {wall.get('applicable')!r}")
        # The schema-domain prefix form, IFC2X3 only.
        motor = psets.get("Pset_ElectricMotorTypeCommon", {})
        check("IfcElectricMotorType" in motor.get("applicable", []),
              f"the domain prefix was not stripped: "
              f"{motor.get('applicable')!r}")
    return problems


def main(argv: list[str]) -> int:
    if not SRC.is_dir() or not any(SRC.iterdir()):
        print(f"no sources in {SRC} — run ./dev/schema/fetch.sh first",
              file=sys.stderr)
        return 2

    verify_only = "--verify" in argv
    OUT.mkdir(parents=True, exist_ok=True)
    failures = 0

    for spec in SCHEMAS:
        missing = [name for name in (spec["express"], spec["psets"])
                   if not (SRC / name).is_file()]
        if missing:
            print(f"{spec['name']}: missing {', '.join(missing)}",
                  file=sys.stderr)
            failures += 1
            continue

        warnings: list[str] = []
        table = build(spec, warnings)
        print(f"{spec['name']}: {len(table['entities'])} entities, "
              f"{len(table['psets'])} property sets")
        problems = verify(table) + warnings
        for problem in problems:
            print(f"  !! {problem}")
        failures += bool(problems)

        if not verify_only:
            stem = spec["name"].lower()
            path = OUT / f"{stem}.json.gz"
            # Gzipped: nothing reads this by eye — it is a generated artefact,
            # regenerable from fetch.sh + this file — and the extension loads
            # one schema, lazily, when it needs it. 2 MB of JSON becomes ~200 KB.
            payload = json.dumps(table, separators=(",", ":"),
                                 ensure_ascii=False).encode("utf-8")
            with gzip.open(path, "wb", compresslevel=9) as handle:
                handle.write(payload)
            print(f"  -> {path.relative_to(OUT.parent.parent.parent)} "
                  f"({path.stat().st_size / 1024:.0f} KB, "
                  f"{len(payload) / 1024:.0f} KB raw)")

    if failures and verify_only:
        print(f"{failures} schema(s) failed verification", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
