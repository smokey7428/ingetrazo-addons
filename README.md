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
| `extensions/ifc_editor/` | The IFC attribute/property editor — **in progress**. Its schema tables (776 IFC4 entities, 513 property sets; 653 IFC2X3 entities, 317 sets) are generated and verified; the editing UI and the `.ifc` writer are next. See [`dev/schema/README.md`](dev/schema/README.md). |
| `extensions/hello_ingetrazo.py` | Smoke test that proves the toolchain (menu entry, tray panel, document data, model counting). Safe to delete once a real extension exists. |

```bash
./dev/schema/fetch.sh            # once: buildingSMART schemas + property sets
python3 dev/schema/generate.py   # rebuild the shipped tables
python3 dev/schema/test_tables.py
```
