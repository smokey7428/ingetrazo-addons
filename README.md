# IngeTrazo add-ons

Add-ons (extensions) we develop for [IngeTrazo](https://ingetrazo.com/en/), the
open-source 3D modeler for architecture and engineering.

Read [`AGENTS.md`](AGENTS.md) first — it has the API notes, the dev loop and the
traps already hit.

## Quick start

```bash
./dev/check.sh      # byte-compile every extension + check it registers something
./dev/install.sh    # symlink them into IngeTrazo's per-user plugin folder
```

Then **restart IngeTrazo** — extensions are discovered at startup only. The new
entries appear under **Extensions** in the menu bar.

```bash
./dev/uninstall.sh  # remove just the symlinks this project created
```

Checking the install itself (shaders, textures, translations, the bundled
plugins) is a separate, headless thing:

```bash
"/Applications/IngeTrazo.app/Contents/MacOS/ingetrazo" --check
```

## Where things are

| | |
| --- | --- |
| Our extensions | `extensions/` — one `.py` file or one package dir each |
| Installed plugin folder | `~/.local/share/ingetrazo/plugins/` |
| Upstream source (reference) | `reference/ingetrazo/` (git clone, read-only) |
| Community catalog entries | `reference/ingetrazo-extensions/` |

`extensions/` is symlinked, not copied, so what is edited here is what the app
loads — no sync step.

## Writing an extension

An extension is a plain Python file. Its file stem is its identity (it becomes
`app.key` and the prefix of its panel object name), and it is imported by the
app with `core.*` and `tools.*` importable.

```python
from tools.base import Tool

class MyTool(Tool):
    name = "My tool"
    shortcut = None
    description = "What it does, in one sentence."

    def on_activate(self, viewport):
        viewport.flash_status("Doing the thing…", 3000)

    def on_deactivate(self, viewport):
        pass
```

For anything beyond a menu entry — a side panel, overlays, snapping, data saved
in the document — add a module-level `setup(app)`. The full contract is in
`reference/ingetrazo/docs/plugins.md`, with worked examples in
`reference/ingetrazo/plugins/`.

Two rules worth repeating:

* **Never write to the document directly.** Go through the command layer
  (`SnapshotImport` / `set_document_data`) or the change is not undoable.
* **Never touch the document off the main thread.** Relay background results
  through a queued `Signal(object)` connected to a bound method.

## Status

| | |
| --- | --- |
| `extensions/ifc_editor/` | Edit every IFC attribute and property set of a tagged element — 776 IFC4 entities and 513 property sets, or 653/317 for IFC2X3. Its own `.ifc` writer (so the edits reach a file) is still to come. |
| `extensions/openings/` | Parametric doors cut into walls by clicking, with a plan symbol and the scenes that show it in the right view. Windows are the same machinery, and next. |
| `extensions/hello_ingetrazo.py` | Smoke test that proves the toolchain (menu entry, tray panel, document data, model counting). Safe to delete once a real extension exists. |

```bash
./dev/check.sh                   # compile + contract + schema-table check
./dev/test.sh                    # 346 checks, no IngeTrazo and no PySide6 needed
./dev/install.sh                 # then restart IngeTrazo
```
