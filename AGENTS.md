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

## Layout of this project

```
Ingetrazo/
├── AGENTS.md            # this file
├── README.md
├── extensions/          # OUR add-ons — one .py file or one package dir each
├── dev/
│   ├── install.sh       # symlink extensions/* into IngeTrazo's plugin folder
│   ├── uninstall.sh     # remove only OUR symlinks
│   ├── check.sh         # byte-compile + contract-check every extension
│   └── lint.py          # "does it register anything?" — AST check, run by check.sh
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
* Panel object names are the layout's key: renaming a panel loses the user's
  placement.
* `start_hidden=True` without an Extensions-menu action is a panel nobody can
  find — always pair it with `add_menu_action`.
