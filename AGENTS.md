# IngeTrazo add-ons — project memory

Read this first. It records what IngeTrazo is, where everything lives on this
Mac, the plugin API as it actually is in 0.5.8, and the traps already hit.

## What we are doing here

Developing **extensions (add-ons) for [IngeTrazo](https://ingetrazo.com/en/)** —
the open-source 3D modeler for architecture/engineering (GPL-3.0-or-later, by
Marco Sumari Tellez, Peru). IngeTrazo is SketchUp-like: an extension is a
**plain Python file** (or a package directory) that the app discovers at
startup. No plugin SDK to install, no build step, no C++.

* Website: <https://ingetrazo.com/en/> · Extensions page: `/en/extensiones`
* Source: <https://github.com/ingelibre/ingetrazo>
* Community catalog: <https://github.com/ingelibre/ingetrazo-extensions>
* Manual (Spanish): <https://ingetrazo-docs.pages.dev>
* Plugin guide: `reference/ingetrazo/docs/plugins.md` (authoritative — read it)

**First add-on: `ifc_editor`** — full IFC attribute and property-set editing for
tagged elements, IFC2X3 and IFC4, with its own `.ifc` writer. The brief, the
constraints and the design are below.

**Second add-on: `openings`** — parametric doors and windows, placed by clicking
a wall, Revit-style, with a plan symbol and their IFC data. Built; see its own
section below.

## Layout of this project

```
Ingetrazo/
├── AGENTS.md            # this file
├── README.md
├── extensions/          # OUR add-ons — one .py file or one package dir each
│   ├── ifc_editor/          # the IFC field/property editor
│   │   ├── __init__.py      # setup(app): the panel + the Extensions-menu entry
│   │   ├── schema.py        # the schema tables, and the questions asked of them
│   │   ├── store.py         # identity, per-element storage, the undo command
│   │   ├── panel.py         # the tray panel that follows the selection
│   │   └── data/            # generated schema tables, ~160 KB each, committed
│   └── openings/            # parametric doors, cut into walls by clicking
│       ├── params.py        # the parameters and what they mean
│       ├── geometry.py      # every part, as plain coordinates — no Qt
│       ├── opening.py       # where the opening goes, and cutting the wall
│       ├── object.py        # the door as a document object + its command
│       ├── host.py          # the guarded private-API shim (tool registration)
│       ├── tool.py          # click a wall to place a door
│       ├── panel.py         # the Doors tab
│       └── scenes.py        # Plan / Elevation / 3D, so the symbol shows
├── dev/
│   ├── install.sh       # symlink extensions/* into IngeTrazo's plugin folder
│   ├── uninstall.sh     # remove only OUR symlinks
│   ├── check.sh         # compile + contract-check + schema-table check
│   ├── test.sh          # run every test in dev/schema and dev/tests
│   ├── lint.py          # "does it register anything?" — AST check, run by check.sh
│   ├── tests/           # extension tests, with stubs for core.* and PySide6
│   └── schema/          # IFC schema tables: fetch, generate, test (see its README)
└── reference/           # shallow clones of upstream (gitignored, read-only)
    ├── ingetrazo/            # app source — the API ground truth
    └── ingetrazo-extensions/ # catalog entries (extensions/*.toml) + tooling
```

`reference/` is cloned at a depth of 1. Refresh with
`git -C reference/ingetrazo pull --depth 1`.

## Environment facts (this machine)

| Thing | Value |
| --- | --- |
| IngeTrazo installed | `/Applications/IngeTrazo.app` — **0.5.8**, PyInstaller bundle (Intel+ARM dmg), 12 Oct |
| App plugins (read-only) | `/Applications/IngeTrazo.app/Contents/Resources/plugins/` |
| Bundled example extensions | `.../Contents/Resources/examples/extensions/` — `niveles.py`, `windowizer.py`, `propiedades_poligono.py` |
| **Our plugin folder** | **`~/.local/share/ingetrazo/plugins/`** |
| Already installed there | `ingefloor`, `ja_sun`, `make_stair`, `niveles`, `node_editor`, `opentrace_bim`, `pointcloud_splat` |
| Logs | `~/Library/Logs/IngeTrazo/ingetrazo-gl.txt`, `ingetrazo-crash.log` |
| Extension screenshots cache | `~/Library/Application Support/IngeTrazo/IngeTrazo/extension-screenshots/` |
| Python 3.12 required | 3.12+ ; system `python3` is 3.12.13 (anaconda) |

### The macOS plugin-folder gotcha

`core/extensions.py::user_plugins_dir()` only special-cases `win32`; **macOS
falls into the "else" branch and uses XDG semantics**:

```
$XDG_DATA_HOME or ~/.local/share   →  .../ingetrazo/plugins
```

So on macOS the folder is `~/.local/share/ingetrazo/plugins` — **not**
`~/Library/Application Support/`. The docs only mention Linux and Windows.
`Extensions ▸ Open plugins folder` creates it.

## The dev loop

Extensions are scanned **once, at startup**, so there is no hot reload.

```bash
./dev/install.sh          # symlink extensions/* into the plugin folder
                          # → then quit and reopen IngeTrazo, or Ctrl+Q / relaunch
./dev/check.sh            # byte-compile + contract-check before restarting
./dev/test.sh             # run the tests (no IngeTrazo, no PySide6 needed)
```

Editing a symlinked file takes effect on the next launch only. There is **no
headless way to load our own extension**: `ingetrazo --check` imports only the
app's *bundled* plugins (`main.py::_self_check`, `root/plugins/*.py`), which is
still worth running to prove the install itself is sound. So the real test is
always the GUI round-trip.

Fastest prototype path is **in the app**: `Extensions ▸ Python Console`
(`Ctrl+Shift+P`) is a live REPL over the open document — every run is ONE undo
step and a run that raises is rolled back whole. `Extensions ▸ Open plugins
folder` reveals the folder for by-hand installs.

Running IngeTrazo **from source** (also viable, needs a venv):

```bash
cd reference/ingetrazo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # PySide6<6.12, numpy, ezdxf, openskp (git), manifold3d
python main.py
```

That is the only way to test against a *newer* API than the installed 0.5.8.
The bundle's own Python is compiled in; we cannot read `core/` out of the app,
which is why the source clone in `reference/` matters.

## The first add-on: `ifc_editor`

**The brief (from the user):** IngeTrazo's control over IFC data is limited.
Add the ability to add and edit *every* available IFC schema field for a
specific element, per IFC4 as published by buildingSMART — for **IFC2X3 and
IFC4**, because the user's own project files are IFC2X3.

**Decided:** the edited fields must reach the exported `.ifc`, and the
extension must be **pure Python, no runtime dependency**.

### Why the design is shaped the way it is — three constraints

1. **There is no exporter hook.** `views/extension_api.py` offers
   `add_file_opener` and nothing else file-related; *"Importer / exporter
   registration"* is still on the upstream roadmap. So an extension **cannot**
   change what *File ▸ Export IFC* writes. The core's writer
   (`formats/ifc.py::save_ifc`) emits only GlobalId (freshly made), Name,
   Tag, geometry and the `Qto_*` quantities — **`Description`, `ObjectType`,
   `PredefinedType` and every `Pset_*` are hardcoded `$`**. Anything we edit
   would be dropped unless we write our own `.ifc`. Hence the extension owns
   its own writer.
2. **Extensions cannot declare dependencies.** `plugin.toml` is roadmap-only,
   nothing in the catalog installs pip packages, and the app bundle ships no
   IFC library (`PySide6`, `numpy`, `ezdxf`, `openskp`, `manifold3d` are the
   bundled set). A catalog extension is a `.py` or a `.zip`. So the schema
   knowledge is reduced, offline, to tables the extension carries.
3. **`scene.mesh` vs `scene.loose_mesh`** and the rest of the data rules below
   still apply — and the only *stable* identities to hang per-element data on
   are `group.uid` (16 hex chars, `core/group.py`) and, for loose-face objects,
   `attrs["ifc"]["id"]`.

### What the core offers today (the thing we are extending)

* The IFC tag is **three fields**: loose faces carry
  `attrs["ifc"] = {"id": int, "class": str, "name": str}`; groups carry
  `group.ifc = {"class", "name"}`; `scene.active_ifc = {"class", "name"}` is
  the tag-as-you-draw state (`core/bim.py`).
* `views/tray.py::BimPanel` (from line 3976) is a class combo box
  (`core.bim.IFC_CLASSES` — 16 curated classes), a name field, Tag / Untag and
  a *Tag as you draw* checkbox. That is the whole existing IFC UI.
* `core/bim.py` also has `class_quantities` (per-class `Qto_*` quantities,
  volume only when the face set is watertight by itself) and `quantities_csv`.
* Upstream's **ROADMAP item #1** is exactly this gap: *"One common BIM API for
  extensions — how a wall, a slab or a window is tagged, **which properties it
  carries**, and how its quantities are computed… so tools from different
  authors fit together."* Unbuilt. We are building ahead of it: design so the
  core can absorb this later rather than fighting it.

### The schema tables — DONE

`extensions/ifc_editor/data/ifc4.json.gz` and `ifc2x3.json.gz`, generated from
buildingSMART's own sources by `dev/schema/`. Read
**`dev/schema/README.md`** for provenance, attribution and the JSON shape;
`dev/schema/test_tables.py` checks the committed artefacts and runs from
`./dev/check.sh`.

Coverage: **776 IFC4 entities, 513 property/quantity sets, every defined type;
653 IFC2X3 entities, 317 sets.** ~160 KB gzipped each. Verified for
referential integrity — every attribute type and every pset's applicable
entity resolves.

### The extension — built

| File | What it is |
| --- | --- |
| `schema.py` | Loads a table (lazily, cached), and answers: a class's attributes in IFC order, whether an entity is a subtype of another, which property sets apply to a class (resolving inheritance *and* the `/PREDEFINEDTYPE` filter), and what kind of value a declared type holds so the right editor can be chosen. |
| `store.py` | Identity, storage and the one command. |
| `panel.py` | The tray tab: schema, a filterable picker over every entity, Name, the class's attributes grouped by declaring entity, every applicable `Pset_*`, custom sets, and read-only measured quantities. |
| `__init__.py` | `setup(app)`: the panel and an Extensions-menu entry (`Ctrl+Shift+I`). |

**Two storages, on purpose.** The **class and name stay in IngeTrazo's own BIM
tag** (`face.attrs["ifc"]`, `group.ifc`) so the BIM panel, the take-off, the CSV
bridge and the core's export never disagree with what our panel shows.
Everything else — description, object type, tag, global id, predefined type,
property sets, your own sets — is ours, in `scene.plugin_data["ifc_editor"]`.
The core has nowhere to put those: it writes them as `$`.

**One edit is one undo step.** `store.EditIfcObject` writes both storages in a
single command and restores both on undo. Going through `set_document_data`
would have been a second step, and `History.undo` does **not** restore the mesh
snapshot — that is only the rollback on failure — so a command has to own its
inverse.

**Identity**: `uid:<group.uid>` for a tagged group, `ifc:<tag id>` for loose
faces, re-resolved from the scene at write time rather than held as a
reference.

### Still to build

**Our own `.ifc` writer.** Until it exists, the fields edited here are saved in
the document but the core's *File ▸ Export IFC* still writes only class, name,
geometry and `Qto_*` — so the extension's data does not yet reach a file. That
writer is the remaining half of the brief and the next piece of work: a
menu action that writes IFC4/IFC2X3 carrying every attribute and property set,
per class, with the real STEP attribute layout (doors and windows take
OverallHeight/OverallWidth in the middle of theirs, `IfcSpace` has `LongName`
where others have `Tag`). `formats/ifc.py` in the core is the reference for the
geometry and the `Qto_*` sets; the tables tell us the rest.

Also worth adding later: tagging untagged geometry from this panel (the class
picker reaches 155 product classes, the core's BIM panel only 16), and reading
an existing `.ifc` back in.

## The second add-on: `openings`

**The brief (from the user):** a door and window panel like Vectorworks or
Revit — control over the individual elements, parametric, **displaying properly
in all views**, and able to carry the needed IFC data.

**Decided:** interactive click-the-wall placement (Revit-like), **one door type
done completely** first, and the plan symbol plus the scenes that make it show
in the right views.

### What already exists to build on — study these first

* **`examples/extensions/windowizer.py`** (1592 lines, ships with the app) is the
  same pattern done for windows, and is the reference for the whole shape of the
  thing: one container group tagged `IfcWindow`, parts (`Frame`, `Glass n`) as
  nested groups each with the same `xform` pose, parameters in `group.ext`, a
  general capture/restore `Command`, an Extensions submenu + right-click menu +
  an `add_outliner_kind` "Type" column. Read it before writing anything.
* **The wall opening is solved**: `mesh.remove_face(host_face)` → four reveal
  quads re-added **carrying the wall's own `attrs`** (material, layer, BIM tag) →
  `mesh.add_hole(back_face, inner)` punches the matching hole so the wall stays
  a closed solid. Windowizer's `cut_opening` / `close_opening`, and its
  `_find_back_face` guard against boring a tunnel to the far facade of a
  single-plane wall.
* Its own warning is inherited by any approach that cuts a freeform wall:
  *"The wall has been edited since, so the opening was not closed for: {names}.
  Close it by hand."* The opening is topology, not an association.
* **The community's 26,000-line parametric BIM extension** (`opentrace_bim`,
  installed on this machine) does walls, slabs, beams, columns — and its
  `openings.py` says doors and windows are **future work**: *"Hosted objects
  (future Windowizer/doors or a universal Opening tool) only describe an opening
  request."* The gap is real and its own authors name it.

### The interactive tool needs private host API

`ExtensionApp` has panels, menus, context menus, overlays, snap providers,
pickables and file openers — but **no tool registration**. `opentrace_bim` works
around it, deliberately isolated in its `host.py`:

```python
for name in ("_tools", "_tool_actions", "_tool_group", "_activate_tool"):
    if not hasattr(app.window, name):
        raise RuntimeError("The tool integration in this IngeTrazo "
                           "installation is not compatible.")
app.window._tools[key] = tool          # register
app.window._activate_tool(key)        # make it the active tool
```

All four exist in 0.5.8. Their comment is the honest summary: *"IngeTrazo 0.5.7
does not expose public tool-registration methods, so the private host
collections are intentionally isolated in this module."* Note also that
`_activate_tool` honours `_tool_filter` (the workspace's `allowed_tools`).

The loader itself sanctions building such a tool — `_builds_bare` only
auto-instantiates plugin `Tool`s that take no argument, and says *"A tool that
needs one … is the extension's to build in its `setup(app)`"*. Building it is
fine; **registering it is the private part**, so keep it behind one guarded
module (`openings/host.py`) exactly as opentrace does.

### Displaying properly in all views — what the platform actually offers

There is **no per-object plan symbol, and no analytic curves.** What exists:

* Plan/section/elevation come from the hidden-line pass in `core/hlr.py`, which
  clips on the **single active section plane**, classifies lines as
  edge/profile/**cut**/hidden, chains the cut chords into fill rings and applies
  poché. So a door modelled as real geometry reads as a proper cut in plan and
  section, for free. This is why the leaf is built **standing open** at
  `open_angle` — the plan cut then matches the swing symbol.
* Arcs are polylines: the Circle and Arc tools emit straight segments, and DXF
  export writes LINE entities only.
* **Layer visibility is one global flag per layer**; a *scene* (`SavedView`)
  snapshots the **names** of hidden layers, and a composer frame inherits a layer
  set **only** by being bound to a `scene:<name>`.
* **A nested group's layer is never consulted**: `world_mesh()` folds children in
  with no visibility filtering, and `collect_geometry` in the HLR walks
  top-level groups only. So the swing arc cannot live inside the door group and
  still be hideable — it goes on the **loose mesh** (where `entity_visible`
  honours `Edge.layer`) or as a **top-level group** of its own.

Design that follows: the door is real geometry; the arc is a real polyline on a
`Doors — plan` layer; the three scenes (Plan / Elevation / 3D) are created with
`SavedView.capture(name, scene, camera)` plus `scene.saved_views.append(...)`,
which an extension can do. And they inherit the wart that a *moved* door leaves
its symbol behind — hence a "Refresh plan symbols" command.

### Built — complete

| File | What it is |
| --- | --- |
| `params.py` | The parameters and what they mean: defaults, tolerant `normalize()` (an unreadable number falls back rather than raising — a door that cannot be rebuilt because one value went bad is worse than a door at 90°), honest `validate()`, and the hinge/swing sign algebra in one place. |
| `geometry.py` | Every part as plain `(x, y, z)` faces — `Frame`, `Leaf`, `Threshold`, `Handle` — plus the swing arc and the opening outline. Pure: no Qt, no scene, no application imports, so the whole of it is testable. One `prism(outline, holes, start, end, plane)` builds a closed solid and orients every face outward. |
| `opening.py` | The frame a door is built in (`axes`), where the opening goes (`plan`), the four reveals, and cutting and closing the wall. |
| `object.py` | The door as a document object: `create` / `rebuild` / `erase`, `preview` for the tool, the bookkeeping in `plugin_data`, the parts as nested groups of one pose, the swing symbol as its own top-level group, and `DoorCommand` — one user action, one undo step. |
| `host.py` | The guarded private-API shim: registering and activating an interactive tool, and reading the point under the cursor. Says why, and refuses gracefully. |
| `tool.py` | `DoorTool` — click a wall, see the opening previewed, click to cut it. Stays active so a plan can be worked through. |
| `panel.py` | The **Openings** tab: the settings for the next door with nothing selected, or the selected door's parameters, rebuilding it where it stands. Changes are coalesced on a short timer — one undo step per settled change, not per arrow key. |
| `scenes.py` | The Plan / Elevation / 3D scenes, and `refresh` to put a moved door's symbol back. |
| `walls.py`, `wall_geometry.py`, `wall_object.py`, `wall_tool.py`, `wall_panel.py` | **A wall of our own**: skins along a polyline, mitred, regenerated from its parameters — so the wall keeps being a wall. The **Walls** panel configures the build-up and **Draw a wall** draws it. |
| `profiles.py` | **The Dutch standards**, in one place: timber sections (kozijnhout 67 × 114, raamhout 54 × 67), glazing (hr++ 20 mm), and the window and door types with their sizes and Dutch names. Adding a type later is a line of data here, not a change to the geometry. |
| `__init__.py` | `setup(app)`: panel, tool, its own submenu, a right-click entry and the Browser's Type column. |

Coordinates: **x** along the wall (0 at the left jamb), **y** into the wall
(0 on the clicked face), **z** up (0 on the floor).

Tests: **243 checks** across `test_openings_geometry.py` (132),
`test_openings_object.py` (73) and `test_openings_panel.py` (38). They prove
each part is a closed solid with a **positive volume** — the same test
`core/bim.py` uses before it will report a volume — that the volumes match the
arithmetic, that the leaf turns correctly for all four handing/swing
combinations at exact angles, that the arc sits on the hinge at the leaf's
radius, that **the wall around an opening is still a closed solid** and comes
back on undo, and that the whole UI path works: the tool places from a click,
the panel edits, the scenes are made and replaced, Erase closes the wall, and
undo walks all of it back.

### Windows

A door and a window are **the same object with different numbers**, which is why
one panel, one tool and one set of geometry build both:

* both are a **frame** lining an opening, made of a section — the width you see
  in elevation (``frame_w``/``frame_h``/``frame_b``) and the depth into the wall
  (``frame_depth``). A frame is its own section deep — kozijnhout 67 × 114, set
  in the wall, with the rest of the reveal finished by somebody else — and
  ``frame_depth`` of 0 means "fill the whole reveal" instead.
* both may have a **part that moves** — a door's leaf, a window's sash — hung on
  a hinge at one side and opening by ``open_angle``;
* both may be **glazed** (``glass_t``), a door usually not, a window always;
* a window stands on a **``sill``** (900 mm by default); a door stands on the
  floor.

| Built in | Opening | Sill | Frame | Sash | Glass |
| --- | --- | --- | --- | --- | --- |
| Vast raam — fixed window | 1000 × 1500 | 900 | kozijnhout **67 × 114** | — | **20 mm** |
| Draairaam — side-hung window | 1000 × 1500 | 900 | kozijnhout **67 × 114** | raamhout **54 × 67** | **20 mm** |
| Stompe deur — hinged door | 1064 × 2082 | 0 | kozijnhout **67 × 114** | leaf 42 mm | — |

A door is ordered by its **leaf**, so its opening is derived: a 930 mm leaf in a
67 mm frame wants a 1064 mm opening, and a 2015 mm leaf wants 2082 mm — the leaf
plus the head member, a door having no bottom member. ``profiles.py`` also
carries the leaf sizes a binnendeur is stocked in (630/730/830/930/1030 ×
2015/2115/2315) for a preset row.

The panel's **kind and type** convert the opening in front of you, like every
other field — so a door can be turned into a window in one undo step, and a vast
raam into a draairaam (which keeps the size and adds the sash).

### Walls of our own — the answer to "the wall stops being a wall"

Because the core has no wall object, an opening cut into freeform geometry is
topology surgery: the wall stops being anything. So the extension now ships a
**wall of its own**, which is the only way this can work without waiting for the
core (upstream's ROADMAP item 4 explicitly puts walls, openings, doors and
windows in *community extensions*).

* `walls.py` — the model: a plan **path**, a **height** and a list of **skins**
  (`name`, `thickness`, `material`) from the outside in, kept in `group.ext`.
  The wall is **centred on the path**, so the skins sit half on either side of
  what was drawn, the way a wall is drawn in a plan.
* `wall_geometry.py` — one **closed solid per skin**, generated from those
  numbers. Multi-skin is the point: a spouwmuur is buitenblad / isolatie /
  binnenblad, three parts, three materials, three volumes.
* `wall_object.py` — the container tagged `IfcWall`, one nested group per skin.
* `wall_tool.py` — draw it like a polyline: click points along the centre line,
  Enter or a double-click finishes, Backspace steps back, Esc cancels. The
  preview is the **real** wall (same generator), skins and all.
* `wall_panel.py` — the **Walls** panel: pick a build-up from
  `profiles.WALLS` (spouwmuur, binnenwand), edit its skins and height, draw.

**Two traps found building it, both by test:**

1. **A shared face is not a solid.** Building each segment of a mitred wall as
   its own prism left the mitre face *inside* the wall: every edge along it
   bordered four faces instead of two, so `core/bim.py` would have refused to
   report a volume at all. A run of mitred segments is therefore built as **one
   extruded band** — `runs()` finds the stretches that mitre as one.
2. **A mitre through the vertex loses nothing.** The intuition that a turn
   "loses the shared square" is true of a *butt* joint, not a mitre: with the
   path as the centre line the mitre line passes through the vertex, so each
   run keeps exactly length × thickness. The skin on the outside of a turn gets
   longer, the one on the inside shorter, and the wall's total is conserved —
   that is the assertion to make, not a per-skin one.

### A wall inside a group cannot be cut

``Viewport.pick_face`` answers with **loose** geometry only — its docstring
filters ``ent_loose`` — so a face that belongs to a group is invisible to it.
That is the platform's own rule, not ours: Push/Pull likewise refuses a face
inside a container "until the group is opened". So the tool works on loose
walls, or on a wall whose group is **open for editing** (then its own faces are
the loose part), and refuses otherwise.

The lesson that cost a round trip with the user: **a tool that picks nothing and
says nothing is unusable.** The hover now uses ``pick_face_any`` — which does see
group-owned faces — purely to tell the two empty cases apart, and reports the
group one with the instructions: double-click into the group, or explode it.

### One limitation, and one still to build

Two openings in the same wall face **must not share a jamb edge**: their holes
would share a boundary edge, and a face whose holes touch is no longer a face
with two holes, so the wall would stop being closed. Put a mullion's worth of
wall between them.

Still to build: the standard-size preset row (the data is already in
``profiles.py``), a top-hung or tilt-and-turn (valraam / draaikiepraam) variant,
and doors and windows of more than one sash.

### The one place we deliberately differ from Windowizer

Windowizer **removes** the face you select, and that only closes up because
its workflow makes you draw a rectangle *on* the wall first, so the wall's own
face already has a hole where the rectangle is. A door cut into the wall's own
face cannot work that way: remove that face and the front rim of the opening
is left open, so the wall stops being a closed solid and silently loses its
volume in the take-off.

So `cut()` **punches a hole** in the host face (and one in the far face) and
joins the two rims with the reveals. Same result, but a door can be cut
anywhere on a wall face, and the wall's own face keeps its identity, its
attrs and its layer. Closing is symmetric: drop the four reveals, fill the two
holes.

Both rims are found again **by the corners of their holes**, never by holding a
face object: a face cannot be saved in the document, and after an undo it is
not the same object anyway.

### Installed

`./dev/install.sh` links it; **Extensions ▸ Doors & windows**, and the **Doors**
tab. The interactive tool registers through `host.py`, the one private-API
dependency — that module refuses gracefully on a build that has moved those
members, so a future IngeTrazo shows a sentence instead of a traceback.

## Plugin API — the essentials (0.5.8 / API_VERSION 2)

**The API is explicitly unstable during 0.x.** Pin behaviour to a version and
re-test after each IngeTrazo release.

### Discovery rules that bite

* Two folders are scanned: `<app_root>/plugins/` then the user folder.
  **First stem wins** — a file named like a bundled plugin is shadowed.
* Files starting with `_` or `.` are skipped; so are non-`.py` files.
* A package is a directory with `__init__.py`.
* Plugins are imported **by file path under a private module name**. Never
  assume `plugins.yourname` is importable, and never assume the plugin
  directory is on `sys.path`.
* Only `Tool` subclasses **defined in the file** register. Importing
  `LineTool` to subclass it does not duplicate the built-in.
* A broken plugin cannot break the app: a failed import or a constructor raise
  shows a disabled `⚠ name (load error)` entry, traceback to the
  `ingetrazo.plugins` logger.

### Tool subclass (menu entry)

```python
from tools.base import Tool

class HelloTool(Tool):
    name = "Hello"                 # Extensions menu label
    shortcut = None                # or "Ctrl+Shift+H"; dropped silently if taken
    description = "Say hello."     # status bar + F3 search

    def on_activate(self, viewport):   # one-shot: menu tools do not become active
        viewport.flash_status("Hello!", 3000)

    deactivate → def on_deactivate(self, viewport): pass
```

Spatial tools override `on_click` / `on_hover` / `on_cancel` and receive a
`ToolContext` (snapped world point, screen position, modifiers, snap metadata).
See `tools/base.py` (711 lines) and `AxisMagnet` for inference behaviour.

### `setup(app)` — anything more than a menu entry

Called once when the main window is built, with an `ExtensionApp`
(`views/extension_api.py`, `API_VERSION = 2`). A plugin may have tools, a
`setup`, or both. If `setup` raises, the plugin shows as a load error and the
app still opens. `app.key` is the file stem.

| Call | Notes |
| --- | --- |
| `app.document_data(default=None)` | ONE JSON-safe value per extension, saved in the `.igz`, reset by New/Open. Returns a **copy** — change it via `set_document_data`. |
| `app.set_document_data(value)` | one undo step; the document becomes unsaved. |
| `app.on_document_changed(fn)` | edits, undo, New, Open. |
| `app.add_panel(title, widget, name=None, *, panel=None, stretch=0, start_hidden=False)` | side-tray tab. Object name `extension_<key>` / `extension_<key>_<name>` — **keep it stable**, the layout is remembered by it. Asking again returns the existing dock (the new widget is ignored). `panel=` puts several extensions in ONE tab. `start_hidden` panels are only listed in Window ▸ Panels. |
| `app.show_panel(dock)` | bring to front, re-show if hidden. |
| `app.add_menu_action(text, fn, shortcut=None, tip=None)` | Extensions menu entry; taken shortcuts are left off; `tip` feeds status bar and F3. |
| `app.add_menu(title)` | `QMenu` submenu for a multi-command extension. |
| `app.add_context_menu(fn)` | `fn(menu, selection)` for the viewport right-click menu. **Open dialogs with `QTimer.singleShot(0, …)`** so the menu closes first. |
| `app.add_outliner_kind(fn)` | `fn(group)` → `{"type": ..., "props": [...]}` for YOUR groups, `None` otherwise. Asked for **every row** — keep it cheap. |
| `app.add_overlay(fn)` | `fn(viewport, painter)`, QPainter over every frame; painter state is saved/restored. Raising once gets it logged and removed. |
| `app.world_to_pixels(points)` | `(N,3)` world metres → `(px, py, in_front)`. Skip `in_front == False`. |
| `app.add_snap_provider(fn)` | `fn(viewport, snap, px, py)` → `SnapResult` or `None`. Never overrides a named point (endpoint/midpoint/centre/intersection) — the user aimed at it. |
| `app.add_pickable(pick, on_select=None, delete=None)` | select your own items with the Select tool, delete with Supr. `pick` is asked **before** model geometry. `delete` must go through `set_document_data` (one undo step). |
| `app.release_pick()` | drop your own selection without a callback. |
| `app.add_file_opener(suffix, fn)` | own document type. `.igz .dae .skp .dxf .dwg .obj .stl .glb` are **refused** (logged, not raised), as is a suffix another extension claimed. |
| `app.enter_workspace(ws)` / `leave_workspace()` / `workspace()` | an extension's own document replaces the model; model is parked untouched. Provisional in 0.x. |
| `group.ext = {app.key: {...}}` | per-group parameters of yours: survive copies, saved in the `.igz`, separate from `group.ifc`. |

### Mutating the document — always through the command layer

Read anything you like. To **write**, do it so it is undoable:

```python
from core.history import SnapshotImport

def on_activate(self, viewport):
    def mutate(scene):
        scene.mesh.add_face([...])          # mesh / group / layer edits
    viewport.history.execute(SnapshotImport(mutate))
    viewport.notify_scene_changed()
```

`ai.run_transactional(viewport, code, scope)` does the same for generated code
with the console's guarantees.

### Honest data points (what the app itself reads)

* geometry: `scene.loose_mesh` — **NOT `scene.mesh`**, which is swapped while a
  group is open for editing; `scene.groups`; instances through
  `core.group.iter_placements(group)` → `[(placed_group, matrix), …]`
* materials: per-face `attrs["color"]` (floats 0–1) and `attrs["texture"]` are
  the render truth; named identity is `scene.materials` + face `attrs["mat"]`
  (`core/materials.py`)
* BIM: `core.bim` — `tag_faces`, `tag_group`, `collect_objects` (same calls as
  the BIM tray and the IFC export)
* lengths: `scene.dimension_style` + the viewport's `_format_dim_value`
* also on scene: `layers`, `dimensions`, `text_labels`, `guides`, `saved_views`,
  `geo_paths`, `plugin_data`

Worked examples in `reference/ingetrazo/plugins/`: `model_info.py`
(read-only dialog), `python_console.py`, `solid_inspector.py` (tray tab +
overlay), `render_blender.py` (full panel extension: folding sections, child
process, document data), `ai_bridge.py` (socket server + main-thread relay).

### Threading rule (non-negotiable)

Never touch the document off the main thread. Relay results with a
`Signal(object)` on a **queued** connection to a bound method. Two traps the
upstream authors hit: `Signal(dict)` hands the slot a **copy** of the payload,
and a **lambda** receiver runs on the **wrong thread**.

## Writing user-facing text

Extensions bring **their own** words; the core's `i18n/*.json` catalogues stay
the core's. Pattern used by `niveles.py` and `propiedades_poligono.py`:

```python
from core.i18n import current_language

_TEXTS = {"es": {"Levels": "Niveles"},
          "pt-BR": {"Levels": "Níveis"}}   # English is the source language

def _t(text: str, **kw) -> str:
    out = _TEXTS.get(current_language(), {}).get(text, text)
    return out.format(**kw) if kw else text
```

English keys pass through untranslated, so a missing entry degrades to English
rather than a cryptic key. The catalogues want **es**, **en** and **pt** in the
entry TOML; Spanish + English is the minimum worth shipping.

## Publishing to the community catalog (when we get there)

The catalog shows what has a ficha in `reference/ingetrazo-extensions/`. It is
a **directory, not a store**: the code lives in our own public repo, the entry
is `extensions/<id>.toml`, copied from `TEMPLATE.toml`. Key fields: `id`,
`version`, `author`(+`author_url`), free `license`, `repository`, `download`
(pinned to a **tag or commit, never `main`**), `sha256` of that exact file,
`ingetrazo` version tested, 1–4 `tags`, `[name]`/`[summary]` in es/en/pt.

`sha256sum my_extension.py` — if it is wrong the robot tells us the right
value. A maintainer then reads the code (**Reviewed**), otherwise it shows as
**Community**. New versions go back to Community until re-read. Entries that
come from the GitHub account in `author_url` and touch only their own ficha
publish themselves.

## Licensing

IngeTrazo is GPL-3.0-or-later. An extension that imports `core.*`/`tools.*` is a
derivative work — ship it **GPL-3.0-or-later** and keep the SPDX header, or
keep it purely a plugin contract. Do not paste GPL code into a differently
licensed project.

**buildingSMART attribution is required** for anything derived from the IFC
schemas and property-set definitions — their licence permits use in software
development and translation into another language only *with full
attribution*. Every generated table carries an `attribution` field and
`dev/schema/README.md` spells it out; keep both. Any surface that shows IFC
classification data to a user should name buildingSMART.

## Our conventions

* One extension per file in `extensions/`, or one directory with `__init__.py`
  when it grows (assets, submodules).
* File stem is the extension's identity — it is `app.key` and the panel object
  name prefix. Lowercase, digits and `_`.
* Header on every file:
  ```python
  # SPDX-License-Identifier: GPL-3.0-or-later
  # Copyright (C) 2026 <author>.
  """What it does, and which IngeTrazo version it was tested with."""
  ```
* Comments, docstrings and commit messages in **English**, even though the
  user's day-to-day language is Dutch and the upstream project is Spanish.
* Never hardcode user-facing English without routing it through `_t()`.
* `./dev/check.sh` before every restart of the app.

## Traps already hit

* **macOS plugin folder is XDG**, not Application Support (see above).
* Extensions load at **startup only** — "my change did nothing" almost always
  means the app was not restarted.
* A file that parses but defines **no `Tool` subclass and no `setup(app)`**
  loads fine and does nothing: the menu stays empty and the log stays silent.
  `dev/lint.py` exists for exactly this.
* `scene.mesh` is the *editing* mesh, swapped while a group is open — use
  `scene.loose_mesh` for totals.
* A `delete`/pickable change that skips `set_document_data` is not undoable and
  desyncs the document.
* The core's IFC **export cannot be extended**: `Description`, `ObjectType`,
  `PredefinedType` and every `Pset_*` are written as `$` by `formats/ifc.py`,
  and there is no exporter registration. Extended data needs our own writer.
* **IfcOpenShell is not in the app bundle**, and no extension can declare a pip
  dependency. Anything an extension imports must be stdlib, bundled
  (`PySide6`, `numpy`, `ezdxf`, `openskp`, `manifold3d`) or shipped inside the
  extension package.
* `standards.buildingsmart.org` answers **403** without a browser-like
  `User-Agent` header.
* The published `ApplicableEntity` of a property set is a **comma-separated
  list**, may carry a **domain prefix** (`IFCELECTRICALDOMAIN/…`, IFC2X3) or a
  **predefined-type filter** (`IfcCovering/FLOORING`), and the IFC2X3 files
  contain stray spaces around some measure names. All three are handled in
  `dev/schema/generate.py` and covered by tests.
* Do not build expectations on the exact entity or property count of a schema
  — the counts live in `dev/schema/test_tables.py` precisely so that a schema
  revision cannot pass unnoticed.
* Panel object names are the layout's key: renaming a panel loses the user's
  placement.
* `start_hidden=True` without an Extensions-menu action is a panel nobody can
  find — always pair it with `add_menu_action`.
* **`History.undo` does not restore the mesh snapshot.** Only a *failed*
  command gets that (`History.execute`'s rollback). Every command must implement
  its own inverse, and anything outside the mesh (group tags, `plugin_data`,
  layers, views) is invisible to the snapshot anyway.
* **The core's own BIM tagging is not undoable** — `BimPanel._on_tag` calls
  `tag_faces`/`tag_group` and then just bumps `scene.version`. Going through the
  command layer, as `ifc_editor` does, is better than the panel it extends.
* **A `Group` has a `uid` before it is tagged.** Keying an element on the uid
  alone makes untagged geometry look like an IFC object; the tag is what makes it
  one (`group.ifc`, `face.attrs["ifc"]`).
* **An empty `plugin_data[key]` is not the same as no key.** `core/scene.py`
  asks whether `scene.plugin_data` is empty to decide if a document has anything
  in it, so a hollow entry left behind makes an empty document look used. Remove
  the key when there is nothing to store — `SetPluginDataCommand` does the same.
* **`FoldSection.body` has no layout of its own**; the caller installs one. The
  idiom is `wrapping_form(section.body)`, which puts labels above fields when the
  tray is narrow.
* **A panel that follows the selection must distinguish the states that are not
  a record** — "nothing selected" and "selected, but not an IFC object" show
  different things. A signature of "the record or None" collapses them, and the
  second never refreshes.
* **PySide6 cannot be imported from the app bundle outside the frozen app**:
  shiboken's bootstrap fails on a missing path. Headless tests therefore stub Qt
  (`dev/tests/qt_stubs.py`) — which exercises logic, not looks.
* **Clear a layout the Qt way**: `takeAt` returns a layout *item* whose
  `widget()` is a method, and a layout added without a parent widget leaves its
  own children parentless, so they linger as stray top-level windows. Put
  everything in the host as a widget, and `deleteLater()` it; do not reparent to
  `None`.
* **An extension's own edits must put its tab back in front.** Editing notifies
  the whole window — every tray refreshes — and in a tabbed tray another panel's
  tab can end up in front of the field the user is about to fill in next. So an
  editing panel re-raises its own dock after a write (`app.show_panel(dock)`),
  but only while that dock is still visible, so a panel the user closed from
  Window ▸ Panels is not resurrected. No code in the app raises a dock on a scene
  change, so when it happens it is Qt's own tab handling — which is why the fix is
  to be explicit about it rather than to hunt a culprit.
* **`add_menu_action` does not check the app's own shortcuts**, only the ones
  other *extensions* took (`_ext_taken_keys`). Asking for one the app already has
  makes both ambiguous. In 0.5.8 the taken `Ctrl+Shift+<letter>` keys are
  **A C G H I N P V Z** — refresh with
  `grep -rhoE '"Ctrl\+Shift\+[A-Za-z]"' views/ core/ | sort -u`.
* A panel that follows the selection should **not rebuild the form when nothing
  it shows has changed**. A rebuild destroys the widget the user is typing in, and
  Qt hands the focus on — which in a tabbed tray means another panel's tab. Compare
  a signature of the record and rebuild only when it differs; set that signature
  around our own writes so the notification they cause does not rebuild.
* A stub that is *wrong* hides real bugs as effectively as real code: the
  class-change rebuild looked broken until `takeAt` was stubbed to Qt's shape,
  and a no-op `narrow()` in the stub hid that it shrinks a button to a 40 px
  sliver. **`narrow()` is for controls that must shrink with the tray** — combo
  boxes, spin boxes, line edits. Applied to a `QPushButton` in a row *with* a
  stretch it sets the horizontal policy to `Ignored`, and Qt then gives the
  button only the 40 px minimum the same helper sets: a button reading "P…",
  which is a button you do not have. A button in a button row wants its own
  size (`setMinimumWidth(button.sizeHint().width())`); the shipped panels only
  every `narrow()` a button in a *vertical* layout, where it is harmless.
* **Build a solid's faces, then orient each one outward.** A prism's side quad
  runs the loop one way and the sweep the other, so its Newell normal comes out
  opposite to the direction you computed — `_face` in `windowizer.py` exists for
  exactly this, and `geometry._oriented` does the same. The symptom is a
  *negative* volume from a shell that is otherwise perfectly closed.
* **Test a solid by its volume, not by its faces.** Positive volume is the same
  condition `core/bim.py` uses before it will report one, so a part that fails it
  would silently have no quantity in the take-off.
* An *arc* is a polyline of straight segments everywhere in this codebase — the
  Circle and Arc tools, the HLR and the DXF writer. Never expect a real curve.
* A rotated slab's bounding box is not the arc of its free edge: it extends half
  a thickness across as well. Expectations like that are where a test gets
  written wrong, and the failure looks like a geometry bug.
