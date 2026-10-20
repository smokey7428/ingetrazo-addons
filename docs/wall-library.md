# A wall library: five countries, five languages — the plan

Status: **the data layer is built** (`library.py`, `data/walls/labels.json`,
`data/walls/nl.json`, 288 checks). The picker and the four remaining libraries
are next; the decisions below are settled.

## Goal

A user works in the language they need and draws from the walls their country
actually builds. Twenty per country — ten external, ten internal — as
*starting points*, each one traceable to a published source and marked reviewed
only once a person has signed it off.

Non-goals: no thermal calculation, no performance figures of our own, no new
wall *geometry* (the wall is unchanged — this is a catalogue of skin stacks).

## Why this is more than a JSON file

Today `profiles.WALLS` is two dicts in code, with Dutch skin names as free
strings (`"Buitenblad"`), English material keys (`"Brick"`), and `nl`/`en` names.
At country scale that breaks in three places:

1. **Skin names would freeze in the document.** A wall stores its skins in
   `group.ext`, so a wall drawn in Dutch keeps Dutch layer names when the
   interface is German. 100 walls × ~4 skins × 5 languages = 2,000 strings.
   → **Translate roles, not skins.** A skin becomes
   `{"role": "outer_leaf", …}` and the label comes from a table: ~14 roles
   instead of 400 strings.
2. **Materials are keys in `scene.materials`.** Translate those and one document
   holds `Brick` *and* `Ziegel` for the same material, splitting the take-off.
   → **Materials stay stable keys**, with labels translated for display.
3. **IngeTrazo has no Dutch, and one Spanish.** Its languages are `en, es,
   pt-BR, zh-CN, it, id, fr, de, pl, ru`. So the extension needs its own
   language layer, and `es-ES` / `es-PE` must be distinguishable.

## Data model

### Files

```
extensions/openings/data/walls/
├── labels.json          # role and material labels, all languages, densities
├── nl.json              # Dutch walls
├── en-GB.json           # United Kingdom
├── de.json              # Germany
├── es-ES.json           # Spain
└── es-PE.json           # Peru
```

One file per **library**, each holding both external and internal walls. The
`labels.json` tables are shared, so a German user browsing the Dutch library
sees Dutch wall names with German layer labels — which is the point.

### A wall

```jsonc
{
  "key": "nl.spouwmuur.100-40-60-100",   // stable; a wall may cite it later
  "kind": "exterior",                    // exterior | interior
  "name": {                              // at least this locale + en-GB
    "nl": "Spouwmuur 100-40-60-100",
    "en-GB": "Cavity wall 100-40-60-100"
  },
  "source": "…clause or URL, exact enough to re-check…",
  "checked": "2026-10-20",
  "reviewed": false,                     // true only after a person signs it off
  "default_height": 2700,                // mm; a storey height, a suggestion
  "skins": [                             // outside → inside, mm
    {"role": "outer_leaf",  "thickness": 100, "material": "brick"},
    {"role": "cavity",      "thickness": 40,  "material": "air_cavity"},
    {"role": "insulation",  "thickness": 60,  "material": "insulation_mineral"},
    {"role": "inner_leaf",  "thickness": 100, "material": "block_concrete"}
  ],
  "performance": {                       // present, EMPTY by decision
    "rc": null, "u": null,
    "value_source": null, "value_checked": null
  }
}
```

**Units: the JSON is in millimetres; the extension converts to metres at load**
with one tested function. Wall files are read by people; `group.ext` is metres.
A deliberate boundary, and a test.

### Labels

```jsonc
{
  "roles": {
    "outer_leaf": {"nl": "Buitenblad", "en-GB": "Outer leaf",
                   "de": "Außenschale", "es-ES": "Hoja exterior",
                   "es-PE": "Muro exterior"},
    "insulation": {…}, "inner_leaf": {…}, "cavity": {…}, "render": {…},
    "plaster": {…}, "timber_stud": {…}, "sheathing": {…}, "vapour_barrier": {…},
    "service_void": {…}, "cladding": {…}, "finish": {…}, "screed": {…},
    "masonry_veneer": {…}
  },
  "materials": {
    "brick":          {"density": 1800, "ifc": "Brick",
                       "labels": {"nl": "Baksteen", "en-GB": "Brick", …}},
    "insulation_mineral": {"density": 30,  "ifc": "Mineral wool", …},
    "air_cavity":     {"density": 0,    "ifc": null, …},
    …
  }
}
```

`density` keeps the take-off's mass working (it is per material already).
`ifc` is the IFC material name to write when the export learns materials —
that is the hook for linking performance data to IFC later.

### Performance fields

Present in every wall, **all `null`, and never computed**. They exist so a user
or an office can fill them in from a standard, and so that when we do link them
they map onto what IFC already has:

| our field | IFC, when linked |
| --- | --- |
| `u` | `Pset_WallCommon.ThermalTransmittance` |
| (load-bearing, fire) | `Pset_WallCommon.LoadBearing`, `.FireRating` |
| `rc` | no standard IFC field — kept as our own property |

Nothing is derived from geometry. A number we did not cite does not appear.

## Language and library are separate settings

Two preferences, in `QSettings` (a user preference, not document data):

- **Interface language** — `nl`, `en-GB`, `de`, `es-ES`, `es-PE`. Defaults from
  IngeTrazo's `current_language()`: `de`→`de`, `es`→`es-ES`, anything else→
  `en-GB`. Dutch users get Dutch even though the app has no Dutch.
- **Wall library** — which country's walls the picker offers. Defaults to the
  language's country, and is changeable: *a Dutch office on a Peru project gets
  Dutch menus and Peruvian walls*.

Search is across **all** languages regardless of the display language: typing
"cavity" finds "Spouwmuur", and "Ziegel" finds it too.

## What the user sees

The type picker becomes a real list, not a combo box of two:

- grouped **Exterior / Interior**, searchable;
- each row: name in the chosen language, total thickness, layer count, and a
  **"draft"** marker while `reviewed` is false;
- the skin rows in the panel use translated role labels, with the role shown
  beside the thickness, so the stack reads as a build-up;
- a wall keeps **its own copy** of the stack (as now), so editing a library
  entry never retroactively changes a wall in an issued drawing. The type key is
  stored alongside as provenance only.

## Migration of walls already drawn

Nothing breaks. A stored skin has `{"name": "Buitenblad"}` and no role: on load,
the name is matched case-insensitively against every role label in every
language, and the role is filled in when it matches. A name that matches nothing
stays free text, which is what a hand-written skin is.

## How we source the walls (the honest part)

I draft each build-up from **published typical details** and cite it; every
entry starts `reviewed: false` and shows as a draft until you sign it off.

| Library | What a draft will lean on |
| --- | --- |
| NL | Bouwbesluit / BRG details, NEN 1068 for the vocabulary |
| en-GB | Approved Document Part L, typical cavity and timber-frame build-ups |
| de | DIN 4108 and GEG practice, WDVS and zweischalige constructions |
| es-ES | Código Técnico de la Edificación, DB-HE; fachada ventilada and brick cavity |
| es-PE | Reglamento Nacional de Edificaciones, E.070 albañilería confinada |

**Review checklist for each wall** — four questions, and I would rather you
answer "no" than be polite:

1. Are the layers in the right **order** and the right **thicknesses**?
2. Is the material right (brick vs block, mineral wool vs EPS)?
3. Is this genuinely **common** in that country, or merely permitted?
4. Would you specify it on a real job? If the honest answer is "it's a sketch",
   it does not go in as reviewed.

**Regulations go stale.** `checked` dates each entry; a review pass on a new
IngeTrazo release is the moment to re-check the ones whose standards moved.

## Tests (structure can be tested; content cannot)

- every file parses; keys unique per library; `kind` is exterior or interior;
- skins: 1–8, thickness 10–500 mm, every `role` in `labels.roles`, every
  `material` in `labels.materials`;
- **every role and material used by a library has a label in all five
  languages**, or the load says which is missing — the one place a partially
  translated library would otherwise show blank labels;
- mm → m conversion is exact and is the only place units change;
- a wall with `"Buitenblad"` migrates to `outer_leaf`;
- the count of reviewed vs draft walls is reported (not a failure);
- the ten-external / ten-internal target is reported per library, so a gap is
  visible without being an error while we build up.

## Delivery in four steps

| | | |
| --- | --- | --- |
| **P1** | Data model, label tables, `nl.json` (the two existing walls moved over, plus what we add), the picker, migration, tests | proves the whole pipeline on content we already trust |
| **P2** | Draft the other four libraries, 20 each, all `reviewed: false` with sources | the content push, nothing published as reviewed |
| **P3** | Your review, flags flipped, release 1.2 with the new entries | the library becomes trustworthy |
| **P4** | *Optional:* an office overlay (`~/.local/share/ingetrazo/openings/walls/*.json`) | office standards without a release each time |

## Decided

1. **The five libraries, and a sixth is a file.** `nl`, `en-GB`, `de`, `es-ES`,
   `es-PE`. `library.languages()` reports *any* `*.json` it finds in
   `data/walls/`, so adding `en-US` or `pt-BR` later is a data file and nothing
   else — no code, no list to remember to edit.
2. **Two Spanish label sets that mostly agree.** `es-ES` and `es-PE` differ where
   the trades differ (`aislamiento`/`aislante`, `hoja`/`muro`), and a missing
   label falls back to the other Spanish before it falls back to English.
3. **Library only, for now.** Wall and layer names are translated in five
   languages; the extension's own panel strings stay English + Spanish. A
   German user gets German walls and German layer names, and English buttons.
4. **The panel keeps the height.** A library entry carries its layers and
   nothing about the storey: `height` stays where it is, in the wall and in the
   panel. (The data model still *allows* a height, so a future entry can suggest
   one; nothing uses it today.)

## What building the data layer taught us

Recorded here because each one changes what a wall can honestly say:

1. **A membrane is thinner than a skin may be.** `MIN_SKIN` is 10 mm, so a
   vapour barrier (0.2 mm) cannot be a layer. A build-up that needs one carries
   a `note` instead — the timber-frame entry does exactly that. Lowering the
   limit is a geometry decision, not a data one.
2. **A stud zone is one skin of one material.** The 145 mm insulated stud zone
   of a timber frame is counted as insulation, so its *mass* is the
   insulation's, not the frame's. The entry says so in its note. Modelling
   timber and insulation side by side in one layer needs a composite skin, which
   the generator does not have.
3. **Material keys stay the names `scene.materials` already uses** — `Brick`,
   `Block`, `Insulation` — rather than the lowercase ids this document first
   proposed. Nothing already drawn changes, the take-off does not split
   `Brick` from `Ziegel`, and the translated name is display only. The
   `labels.json` entry carries the density and the IFC material name.
4. **`profiles.WALLS` is now a view of the library**, so the panel, the tool and
   every stored document kept working while the picker is still the old combo
   box: same legacy keys (`spouwmuur`, `binnenwand`), same `(name, thickness,
   material)` skins. The literal fallback in `profiles.py` is what answers if
   the data cannot be read, and a test keeps the two equal so they cannot drift.

## Still open (P1b onwards)

The picker: a searchable, grouped list with a draft marker, in place of the
combo box. And the four remaining libraries, which are the content work.

