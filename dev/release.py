#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Build the release artefacts and the catalog entries.

Two things the community catalog needs, and one rule that shapes both:

* a **download** pinned to a **tag or commit, never a branch** — what a
  maintainer reviews must not change underneath them;
* the **SHA-256 of that exact file**, written into the entry.

So the zips are built here with **fixed timestamps and permissions**: running
this twice on the same source gives the same bytes and therefore the same hash.
A release whose hash changes on every build is a release nobody can review.

Output
    dist/<id>-<version>.zip          one folder per zip, with an __init__.py
    catalog/<id>.toml                the entry, hashes filled in

Usage:  python3 dev/release.py [--version 1.0]
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = ROOT / "extensions"
DIST = ROOT / "dist"
CATALOG = ROOT / "catalog"

#: Where the extensions live publicly. One repository, one tag per extension.
REPOSITORY = "https://github.com/smokey7428/ingetrazo-addons"
AUTHOR = "Eric Smook"
AUTHOR_URL = "https://github.com/smokey7428"

#: The IngeTrazo version they were tested with.
INGETRAZO = "0.5.8"

#: One entry per extension: what it is called and what it says it does, in the
#: three languages the catalog asks for.
ENTRIES = {
    "ifc_editor": {
        "tags": ["bim", "import-export"],
        "name": {
            "es": "Campos IFC — editor completo",
            "en": "IFC fields — full editor",
            "pt": "Campos IFC — editor completo",
        },
        "summary": {
            "es": "Edita todos los atributos y conjuntos de propiedades IFC de "
                  "un elemento, con los 776 tipos de IFC4, y exporta un .ifc "
                  "que los lleva, incluidos los huecos de los muros.",
            "en": "Edit every IFC attribute and property set of an element, "
                  "across all 776 IFC4 entities, and export an .ifc that "
                  "carries them — including the openings in walls.",
            "pt": "Edite todos os atributos e conjuntos de propriedades IFC de "
                  "um elemento, com as 776 entidades IFC4, e exporte um .ifc "
                  "que os leva, incluindo os vãos das paredes.",
        },
    },
    "openings": {
        "tags": ["architecture", "bim", "structures"],
        "name": {
            "es": "Muros, puertas y ventanas",
            "en": "Walls, doors and windows",
            "pt": "Paredes, portas e janelas",
        },
        "summary": {
            "es": "Muros multicapa dibujados como polilínea (67 × 114, 54 × 67, "
                  "cristal de 20 mm) con puertas y ventanas paramétricas "
                  "alojadas en ellos, y un metrado por capa.",
            "en": "Multi-skin walls drawn as a polyline (kozijnhout 67 × 114, "
                  "raamhout 54 × 67, 20 mm glass) with parametric doors and "
                  "windows hosted in them, and a take-off per skin.",
            "pt": "Paredes multicamada desenhadas como polilinha (67 × 114, "
                  "54 × 67, vidro de 20 mm) com portas e janelas "
                  "paramétricas alojadas nelas, e um orçamento por camada.",
        },
    },
}

#: Fixed metadata, so the same source always zips to the same bytes.
_FIXED_TIME = (2026, 1, 1, 0, 0, 0)
_MODE = 0o644


def package_of(name: str) -> Path | None:
    """The extension's directory when it is a package, else its file."""
    folder = EXTENSIONS / name
    if folder.is_dir() and (folder / "__init__.py").is_file():
        return folder
    single = EXTENSIONS / f"{name}.py"
    return single if single.is_file() else None


def build_zip(name: str, version: str) -> Path:
    """Zip one extension so it installs as one folder (or one file)."""
    source = package_of(name)
    if source is None:
        raise SystemExit(f"no extension called {name!r} in {EXTENSIONS}")
    DIST.mkdir(parents=True, exist_ok=True)
    target = DIST / f"{name}-{version}.zip"

    files = []
    if source.is_dir():
        files = sorted(path for path in source.rglob("*")
                       if path.is_file()
                       and "__pycache__" not in path.parts
                       and not path.name.startswith("."))
    else:
        files = [source]

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            # The catalog expects ONE folder at the root, holding __init__.py.
            if source.is_dir():
                inside = Path(name) / path.relative_to(source)
            else:
                inside = Path(name + ".py")
            info = zipfile.ZipInfo(str(inside).replace("\\", "/"), _FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _MODE << 16
            archive.writestr(info, path.read_bytes())
    return target


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry_toml(name: str, version: str, digest: str) -> str:
    """The catalog entry, ready to drop into ``extensions/<id>.toml``."""
    meta = ENTRIES[name]
    download = (f"{REPOSITORY}/releases/download/{name}-v{version}/"
                f"{name}-{version}.zip")
    lines = [
        f'id = "{name}"',
        f'version = "{version}"',
        f'author = "{AUTHOR}"',
        f'author_url = "{AUTHOR_URL}"',
        'license = "GPL-3.0-or-later"',
        f'repository = "{REPOSITORY}"',
        f'download = "{download}"',
        f'sha256 = "{digest}"',
        f'ingetrazo = "{INGETRAZO}"',
        "tags = [" + ", ".join(f'"{tag}"' for tag in meta["tags"]) + "]",
        "",
        "[name]",
    ]
    lines += [f'{lang} = "{text}"' for lang, text in meta["name"].items()]
    lines += ["", "[summary]"]
    lines += [f'{lang} = "{text}"' for lang, text in meta["summary"].items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    version = "1.0"
    if "--version" in argv:
        version = argv[argv.index("--version") + 1]
    CATALOG.mkdir(parents=True, exist_ok=True)

    for name in ENTRIES:
        zip_path = build_zip(name, version)
        digest = sha256(zip_path)
        toml = CATALOG / f"{name}.toml"
        toml.write_text(entry_toml(name, version, digest), encoding="utf-8")
        print(f"{name} {version}")
        print(f"  zip    {zip_path.relative_to(ROOT)}  "
              f"({zip_path.stat().st_size / 1024:.0f} KB)")
        print(f"  sha256 {digest}")
        print(f"  entry  {toml.relative_to(ROOT)}")
    print("\nTag each one in the repository before submitting:")
    for name in ENTRIES:
        print(f"  {name}-v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
