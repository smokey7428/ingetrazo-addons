# IFC schema tables

The IFC knowledge the `ifc_editor` extension ships, and the generator that
produces it. Nothing here runs at extension runtime — it is a build-time step
whose compact output is committed.

```
fetch.sh         download the third-party sources into src/   (not committed)
express.py       read a buildingSMART EXPRESS schema (.exp)
spf.py           read a STEP Physical File (.ifc)
generate.py      build extensions/ifc_editor/data/*.json.gz
test_tables.py   check the committed tables — runs without src/
src/             the downloaded sources, gitignored
```

```bash
./dev/schema/fetch.sh                # once, and again only to move schema version
python3 dev/schema/generate.py       # write the tables
python3 dev/schema/generate.py --verify   # build in memory, check, write nothing
python3 dev/schema/test_tables.py    # check what is committed
```

## Why tables instead of a runtime dependency

An IngeTrazo extension has to be self-contained. There is no dependency
mechanism (upstream's `plugin.toml` is still roadmap), the app bundle ships no
IFC library, and the community catalog installs a `.py` or a `.zip` — nothing
that can pull in a native wheel. A runtime schema lookup would therefore mean
either shipping the whole schemas or asking every user to `pip install` by
hand into the app's bundled Python, which breaks on the next release.

So the schema is reduced once, offline, to tables small enough to ship, and
the extension reads them from its own `data/` directory. `ifcopenshell` is
*discussed* in the project as a dev-time oracle, not a runtime dependency —
the same choice upstream made for their IFC writer.

## Sources and attribution

The tables are **derived data**, not copies, but they would not exist without
these:

| Source | From | Used for |
| --- | --- | --- |
| `IFC4.exp` | [buildingSMART](https://standards.buildingsmart.org/IFC/RELEASE/IFC4/ADD2_TC1/EXPRESS/IFC4.exp) — IFC4 ADD2 TC1 | all 776 entities: ordered attributes, types, optionality, enumerations, inheritance |
| `IFC2X3_TC1.exp` | [buildingSMART](https://standards.buildingsmart.org/IFC/RELEASE/IFC2x3/TC1/EXPRESS/IFC2X3_TC1.exp) — IFC2x3 TC1 | the same for the 653 IFC2X3 entities |
| `Pset_IFC4_ADD2.ifc` | bSI's property-set definitions, as distributed with [IfcOpenShell](https://github.com/IfcOpenShell/IfcOpenShell) | 513 property and quantity sets, their properties and their applicable entity |
| `Pset_IFC2X3.ifc` | ditto | 317 sets for IFC2X3 |

buildingSMART International Limited holds the copyright on the IFC
specification. Their licence permits photocopying, use in software development
and translation into another computer language **provided full attribution is
given** — which is why every generated table carries an `attribution` field and
why this file exists. Do not strip either.

The `Pset_*.ifc` files are fetched from a **pinned commit** of IfcOpenShell
(`2fae1dea0db318c8d0a72e2cd956a9b8c0d7fd0e`), never from a branch: what is
reviewed and shipped must not change underneath us. The download is 3.8 MB and
is not committed; the generated tables are, because they are what the
extension reads.

Note that `standards.buildingsmart.org` answers **403** to a request without a
browser-like `User-Agent`; `fetch.sh` sets one.

## What the tables contain

One gzipped JSON per schema, `extensions/ifc_editor/data/ifc4.json.gz` and
`ifc2x3.json.gz` (~150 KB each, 1.3 MB raw):

```jsonc
{
  "schema": "IFC4",
  "generated": "2026-10-17",
  "attribution": "…",
  "sources": { "IFC4.exp": "…", "Pset_IFC4_ADD2.ifc": "…" },

  "entities": {
    "IfcWall": {
      "supertype": "IfcBuildingElement",
      // Attributes in the order IFC writes them: inherited first, then its
      // own. `inherited_from` names the declaring entity; `enum` and `select`
      // carry the alternatives a field can take.
      "attributes": [
        { "name": "GlobalId", "type": "IfcGloballyUniqueId",
          "inherited_from": "IfcRoot" },
        { "name": "PredefinedType", "type": "IfcWallTypeEnum",
          "optional": true, "enum": ["ELEMENTEDCASE", "MOVABLE", "…"] }
      ],
      // Convenience: the PredefinedType attribute and its values, if it has
      // one. IFC2X3 moved PredefinedType onto the *Type entities, so plenty
      // of IFC2X3 occurrences have none.
      "predefined_type": { "attribute": "PredefinedType",
                           "type": "IfcWallTypeEnum", "values": ["…"] }
    }
  },

  // Every defined TYPE, so an attribute's declared type always resolves and
  // an editor can tell a measure from a text field.
  "types": {
    "IfcLabel":        { "kind": "string", "size": 255 },
    "IfcPositiveInteger": { "kind": "alias", "of": "INTEGER" },
    "IfcShell":        { "kind": "select", "values": ["IfcOpenShell", "…"] },
    "PEnum_ElementStatus": { "kind": "enum", "values": ["NEW", "…"] }
  },

  "psets": {
    "Pset_WallCommon": {
      "template_type": "PSET_TYPEDRIVENOVERRIDE",
      "kind": "pset",                     // or "qto" for quantity sets
      "applicable": ["IfcWall"],          // entity, or "Entity/PREDEFINEDTYPE"
      "properties": [
        { "name": "IsExternal", "value_type": "IfcBoolean",
          "property_type": "P_SINGLEVALUE", "description": "…" }
      ]
    }
  }
}
```

### Two quirks of the published `ApplicableEntity` field

Both are handled, and both have a regression test, because both are easy to
get wrong:

* it is a **comma-separated list**, not one name — IFC2X3's `Pset_WallCommon`
  applies to `IfcWall` *and* `IfcWallStandardCase`;
* a token may carry a **domain prefix** (`IFCELECTRICALDOMAIN/IfcElectricMotorType`,
  IFC2X3 only) or a **predefined-type filter** (`IfcCovering/FLOORING`, meaning
  only coverings whose `PredefinedType` is `FLOORING`).

An entity name always starts with `Ifc`, so the entity is the first token part
that does: a trailing part is the filter, a leading one is a domain.

The IFC2X3 files also contain stray spaces around some measure names
(`' IfcElectricCurrentMeasure'`), which are stripped on generation.

## Updating to a newer schema revision

Change the URLs in `fetch.sh`, re-run it, run `generate.py`, and check
`test_tables.py` — the expected counts at the top of that file will have to
move with the schema, which is the point: a silent change in entity or property
count should not pass unnoticed.
