# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""The wall library: what each country builds, in the language you work in.

A wall build-up is *data*, not code. One JSON file per library — ``nl.json``,
``en-GB.json``, ``de.json``, ``es-ES.json``, ``es-PE.json`` — each a list of
walls, and one shared ``labels.json`` holding the words.

Two things follow from that split, and they are the whole reason for it:

* **A layer stores a role, not a name.** ``outer_leaf``, not ``"Buitenblad"``.
  The label comes from the table, so a German reader browsing the Dutch library
  sees Dutch wall names with German layer names — and a wall drawn in Dutch does
  not keep Dutch names forever in a document that later changes language.
  Fourteen roles instead of four hundred translated strings.
* **A material stores a key, not a word.** ``"Brick"`` is a name in
  ``scene.materials``; translate it and one document holds ``Brick`` *and*
  ``Ziegel* for the same brick, and the take-off splits. The key is stable, the
  label is translated for display only, and the density travels with the key.

Thicknesses are **millimetres in the files** and **metres here** — one boundary,
in ``_millimetres``, because the files are read by people and ``group.ext`` is
metres everywhere else.

Every entry carries its source and a ``reviewed`` flag. A draft is a draft: it
says where it came from and it says nothing about performance, because this
module does not compute one. The ``performance`` block is present and empty, and
``u`` maps onto ``Pset_WallCommon.ThermalTransmittance`` when the export learns
to carry it.

Pure data: no Qt, no scene, no imports from the application — so the whole of
this is testable, and a broken file is a problem to report rather than an
exception in a panel.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: Where the libraries live, inside the extension.
DATA = Path(__file__).resolve().parent / "data" / "walls"

#: The language a label falls back to when it is not translated. The language
#: the extension's own source is written in.
FALLBACK = "en-GB"

#: The libraries this release ships, in the order the picker offers them. A
#: sixth is a new JSON file and nothing else — ``languages()`` also reports any
#: file it finds that is not listed here.
LOCALES = ("nl", "en-GB", "de", "es-ES", "es-PE")

#: IngeTrazo's language code, and the library vocabulary that answers it. The
#: app has no Dutch, and one Spanish: both are ours to tell apart.
APP_LANGUAGE = {"nl": "nl", "de": "de", "es": "es-ES", "en": "en-GB"}

#: Where a language borrows its words from when a label is missing. Spanish
#: (Peru) and Spanish (Spain) agree on most of the trades; a missing entry falls
#: back to the other before it falls back to English.
SIBLINGS = {"es-ES": ("es-PE",), "es-PE": ("es-ES",)}

#: A storey height, used when a library entry does not carry one — which is the
#: normal case: a height belongs to the storey, not to the build-up.
DEFAULT_HEIGHT = 2.700

#: What a skin may be, in metres. **3 mm**, because that is what the walls are:
#: a render is 6–15 mm and a plasterboard is 12.5, and a library that cannot
#: hold them is a library that lies about the wall. A membrane (0.2 mm) is
#: still below this and is therefore a note rather than a layer.
MIN_SKIN, MAX_SKIN = 0.003, 0.500

#: Skins in one wall, as much as the geometry will take.
MAX_SKINS = 8

_KINDS = ("exterior", "interior")

_cache: dict = {}
_problems: list[str] = []


# ---- reading ---------------------------------------------------------------
def _remember(problem: str) -> None:
    if problem not in _problems:
        _problems.append(problem)


def _note(sink: list | None, problem: str) -> None:
    """Record a problem where the caller is collecting them.

    Loading a shipped library reports to ``problems()``, which the tests
    require to be empty. An **import** collects its own, because it has to show
    them to the person who just chose the file — a wall that could not be read
    must say so where it was asked for, not in a log nobody opens.
    """
    if sink is None:
        _remember(problem)
    else:
        sink.append(problem)


def problems() -> list[str]:
    """Everything the library could not make sense of. Empty is the only
    acceptable answer, and the tests say so — the loading itself never raises,
    so a bad file reaches a user as a missing wall, not as a dead panel."""
    return list(_problems)


def reset() -> None:
    """Forget everything loaded and read it again. For the tests, and for a
    user who has edited a file by hand and wants to see it without a restart."""
    _cache.clear()
    del _problems[:]


def _read(path: Path, default):
    # ``utf-8-sig``: a file edited in Notepad or Excel starts with a byte-order
    # mark, and a BOM must not be the reason a wall library will not load.
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        _remember(f"{path.name} is missing from data/walls")
    except (OSError, ValueError) as exc:
        _remember(f"{path.name} could not be read: {exc}")
    return default


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _millimetres(value) -> float | None:
    """The one place units change: the files are in millimetres, this is metres."""
    number = _number(value)
    return None if number is None else number / 1000.0


# ---- languages -------------------------------------------------------------
def default_language(app_code: str | None = None) -> str:
    """The library language that answers IngeTrazo's own language setting."""
    base = str(app_code or "").split("-")[0].lower()
    return APP_LANGUAGE.get(base, FALLBACK)


def chain(language: str | None) -> tuple[str, ...]:
    """The order a label is looked up in: the language asked for, its siblings,
    its base language, then English."""
    language = language or FALLBACK
    order = [language, *SIBLINGS.get(language, ())]
    base = language.split("-")[0]
    if base != language:
        order.append(base)
    order.append(FALLBACK)
    seen: list[str] = []
    for code in order:
        if code and code not in seen:
            seen.append(code)
    return tuple(seen)


def languages() -> tuple[str, ...]:
    """Which libraries are actually present, in the order to offer them.

    Any ``*.json`` in ``data/walls/`` is a library — that is how a sixth becomes
    a data file and nothing else — and so is any locale the user has imported a
    wall for.
    """
    if "languages" not in _cache:
        # Everything in the folder is a library except the words and the
        # schema — the schema is a .json because editors want one, not because
        # it holds walls.
        found = {path.stem for path in DATA.glob("*.json")} - {"labels",
                                                              "walls.schema"}
        for entry in _user_raw().get("walls") or ():
            if isinstance(entry, dict) and str(entry.get("locale") or "").strip():
                found.add(str(entry["locale"]).strip())
        ordered = [code for code in LOCALES if code in found]
        ordered += sorted(found - set(LOCALES))
        if not ordered:
            _remember("no wall libraries were found in data/walls")
        _cache["languages"] = tuple(ordered)
    return _cache["languages"]


def _locale(locale: str | None) -> str:
    available = languages()
    if locale in available:
        return str(locale)
    if locale:
        _remember(f"there is no {locale} wall library")
    return available[0] if available else FALLBACK


# ---- labels ----------------------------------------------------------------
def labels() -> dict:
    """``{"roles": {role: {language: label}}, "materials": {name: {...}}}``."""
    if "labels" not in _cache:
        raw = _read(DATA / "labels.json", {})
        roles = {}
        for role, entry in (raw.get("roles") or {}).items():
            if isinstance(entry, dict):
                roles[str(role)] = {str(k): str(v) for k, v in entry.items()}
        materials = {}
        for name, entry in (raw.get("materials") or {}).items():
            if not isinstance(entry, dict):
                continue
            materials[str(name)] = {
                "density": _number(entry.get("density")),
                "ifc": entry.get("ifc"),
                "labels": {str(k): str(v)
                           for k, v in (entry.get("labels") or {}).items()},
            }
        if not roles or not materials:
            _remember("labels.json has no roles or no materials")
        _cache["labels"] = {"roles": roles, "materials": materials}
    return _cache["labels"]


def _first(mapping: dict, language: str | None) -> str:
    """The first label in ``mapping`` along the fallback chain, or ``""``."""
    for code in chain(language):
        value = str(mapping.get(code) or "").strip()
        if value:
            return value
    return ""


def role_label(role: str, language: str | None = None) -> str:
    return _first(labels()["roles"].get(str(role or "")) or {}, language)


def material_label(material: str, language: str | None = None) -> str:
    entry = labels()["materials"].get(str(material or "")) or {}
    return _first(entry.get("labels") or {}, language)


def material_density(material: str) -> float | None:
    """kg/m³, or None when we do not know it — a take-off omits the mass rather
    than inventing one."""
    entry = labels()["materials"].get(str(material or "")) or {}
    return entry.get("density")


def material_ifc(material: str) -> str | None:
    """The IFC material name, for a writer that carries materials."""
    entry = labels()["materials"].get(str(material or "")) or {}
    return entry.get("ifc")


def densities() -> dict:
    """Every material we can weigh, ``{name: kg/m³}``."""
    return {name: entry["density"] for name, entry in labels()["materials"].items()
            if entry.get("density") is not None}


def role_for(name: str) -> str | None:
    """Which role a stored, hand-written skin name refers to — in any language.

    This is the migration: a wall drawn before the library existed stores
    ``{"name": "Buitenblad"}``, and ``"Buitenblad"`` is the Dutch label of
    ``outer_leaf``. A name that matches nothing stays free text, which is what a
    skin the user typed is.
    """
    wanted = " ".join(str(name or "").split()).casefold()
    if not wanted:
        return None
    for role, entry in labels()["roles"].items():
        for value in entry.values():
            if " ".join(str(value).split()).casefold() == wanted:
                return role
    return None


# ---- walls -----------------------------------------------------------------
def _document(locale: str) -> dict:
    """A library file as it was written — kept, so an export can hand back the
    entries exactly as they came in, millimetres and all."""
    slot = ("doc", locale)
    if slot not in _cache:
        _cache[slot] = _read(DATA / f"{locale}.json", {})
    return _cache[slot]


def walls(locale: str | None = None) -> tuple[dict, ...]:
    """One library, every wall, thicknesses in metres.

    The user's own walls come after the shipped ones — and a wall of theirs with
    the same key **replaces** it, which is how an office corrects a build-up
    without waiting for a release.
    """
    code = _locale(locale)
    slot = ("walls", code)
    if slot not in _cache:
        loaded = []
        for entry in _document(code).get("walls") or ():
            wall = _wall(entry, code) if isinstance(entry, dict) else None
            if wall is not None:
                loaded.append(wall)
        mine = _user_walls(code)
        if mine:
            mine_keys = {entry["key"] for entry in mine}
            loaded = [e for e in loaded if e["key"] not in mine_keys] + list(mine)
        if not loaded:
            _remember(f"{code}: there are no usable walls")
        _cache[slot] = tuple(loaded)
    return _cache[slot]


def _wall(entry: dict, locale: str, sink: list | None = None) -> dict | None:
    """One entry from a file, checked enough to be trusted by the geometry."""
    key = str(entry.get("key") or "").strip()
    if not key.startswith(locale + "."):
        _note(sink, f"{locale}: a wall's key should start with {locale!r}, "
                    f"got {key!r}")
    if not key:
        _note(sink, f"{locale}: a wall with no key was skipped")
        return None

    kind = entry.get("kind")
    if kind not in _KINDS:
        _note(sink, f"{key}: kind should be exterior or interior, got {kind!r}")
        kind = _KINDS[0]

    names = {str(code): str(value) for code, value in
             (entry.get("names") or entry.get("name") or {}).items()}
    if not names:
        _note(sink, f"{key}: no name in any language")

    known_roles = labels()["roles"]
    known_materials = labels()["materials"]
    skins = []
    for index, skin in enumerate(entry.get("skins") or ()):
        if not isinstance(skin, dict):
            continue
        thickness = _millimetres(skin.get("thickness"))
        if thickness is None or thickness <= 0:
            _note(sink, f"{key}: skin {index + 1} has no readable thickness")
            continue
        if not MIN_SKIN <= thickness <= MAX_SKIN:
            _note(sink, f"{key}: skin {index + 1} is {thickness * 1000:.0f} mm, "
                        f"outside {MIN_SKIN * 1000:.0f}–{MAX_SKIN * 1000:.0f} mm")
            continue
        role = str(skin.get("role") or "").strip()
        if role not in known_roles:
            _note(sink, f"{key}: skin {index + 1} has role {role!r}, which is "
                        f"not in labels.json")
        material = str(skin.get("material") or "").strip()
        if material not in known_materials:
            _note(sink, f"{key}: skin {index + 1} has material {material!r}, "
                        f"which is not in labels.json")
        skins.append({"role": role, "name": "", "thickness": thickness,
                      "material": material})
    if not skins:
        _note(sink, f"{key}: no usable skins, so the wall was skipped")
        return None
    if len(skins) > MAX_SKINS:
        _note(sink, f"{key}: {len(skins)} skins, and {MAX_SKINS} is the most the "
                    f"geometry builds")

    reviewed = entry.get("reviewed", False)
    if not isinstance(reviewed, bool):
        # ``bool("false")`` is True. A string here would silently sign a wall
        # off, which is the one thing this flag exists to prevent.
        _note(sink, f"{key}: reviewed must be true or false, got {reviewed!r}")
        reviewed = False

    performance = entry.get("performance") or {}
    return {
        "key": key,
        "legacy": str(entry.get("legacy") or "").strip(),
        "locale": locale,
        "kind": kind,
        "names": names,
        "skins": skins[:MAX_SKINS],
        "source": str(entry.get("source") or "").strip(),
        "checked": str(entry.get("checked") or "").strip(),
        "reviewed": reviewed,
        "note": str(entry.get("note") or "").strip(),
        "mine": False,
        "performance": {"rc": performance.get("rc"),
                        "u": performance.get("u"),
                        "value_source": performance.get("value_source"),
                        "value_checked": performance.get("value_checked")},
    }


# ---- the user's own wall types --------------------------------------------
#: Where a user's own types are kept. Outside the extension, so updating it
#: never removes them; and beside what the app calls its own data folder, which
#: on macOS is the XDG one (see AGENTS.md: the app special-cases only win32).
#: A test points this at a temporary folder instead.
USER_HOME: Path | None = None


def user_path() -> Path:
    """The file a user's own wall types are kept in."""
    home = USER_HOME
    if home is None:
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA")
                        or Path.home() / "AppData" / "Roaming")
        else:
            base = Path(os.environ.get("XDG_DATA_HOME")
                        or Path.home() / ".local" / "share")
        home = base / "ingetrazo" / "openings" / "walls"
    return Path(home) / "user.json"


def _user_raw() -> dict:
    """What the user has imported. Missing is normal, so it says nothing."""
    path = user_path()
    if not path.is_file():
        return {"walls": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        _remember(f"your own wall types could not be read: {exc}")
        return {"walls": []}
    if isinstance(data, list):
        return {"walls": data}
    return data if isinstance(data, dict) else {"walls": []}


def _user_walls(locale: str) -> tuple[dict, ...]:
    slot = ("mine", locale)
    if slot not in _cache:
        loaded = []
        for entry in _user_raw().get("walls") or ():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("locale") or locale).strip() != locale:
                continue
            wall = _wall(entry, locale)
            if wall is not None:
                wall["mine"] = True
                loaded.append(wall)
        _cache[slot] = tuple(loaded)
    return _cache[slot]


def _write(path: Path, data) -> Path:
    """Write beside the target and move it into place: a half-written file that
    a later load has to survive is not worth the microseconds saved."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)
    return path


def _same(first: dict, second: dict) -> bool:
    """Whether two wall entries say exactly the same thing.

    An imported copy carries the library stamp ``_wall`` and ``import`` add;
    everything else has to match, or it is a wall worth keeping.
    """
    return ({k: v for k, v in first.items() if k != "locale"}
            == {k: v for k, v in second.items() if k != "locale"})


#: What an exported file says about itself, at the top.
EXPORT_NOTE = (
    "Wall types, from IngeTrazo. Edit this file and import it back: the import "
    "checks every wall and tells you what it could not read. Thicknesses are "
    "millimetres, listed from the outside in. A layer names a role "
    "(outer_leaf, insulation, inner_leaf, …) and a material one of the keys "
    "the extension ships — Brick, Block, Timber, Insulation, Air, …  "
    "\"reviewed\": true means a person has checked the build-up; leave it "
    "false for anything you have not.")


def export_library(path, locale: str | None = None,
                   keys=None) -> dict:
    """Write one library — the shipped walls and the user's own — to a file.

    The file is a **library file**: the same shape ``data/walls/nl.json`` has,
    so exporting and importing is one format and one validator, and what is
    exported can be dropped beside the shipped libraries as they are.
    """
    if locale is not None and str(locale) not in languages():
        # Falling back would write the Dutch walls under a German file name.
        raise ValueError(f"there is no {locale} wall library to export")
    code = _locale(locale)
    document = _document(code)
    wanted = None if keys is None else {str(key) for key in keys}
    own = {}
    for entry in _user_raw().get("walls") or ():
        if not isinstance(entry, dict) or not entry.get("key"):
            continue
        if str(entry.get("locale") or code).strip() != code:
            continue
        own[str(entry["key"])] = entry

    entries = []
    for entry in document.get("walls") or ():
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key"))
        if wanted is not None and key not in wanted:
            continue
        # A wall the user corrected **replaces** the shipped one, exactly as the
        # picker shows it: one wall per key, in the shipped order, never two.
        entries.append(own.pop(key, entry))
    for key, entry in own.items():
        if wanted is not None and key not in wanted:
            continue
        entries.append(entry)

    out = {"locale": code,
           "country": document.get("country") or "",
           "note": EXPORT_NOTE,
           "walls": entries}
    # A library file that points at a schema is a library file an editor can
    # check while a person types. The schema travels with the export, so the
    # folder can be handed to somebody else and still validate.
    schema = DATA / "walls.schema.json"
    if schema.is_file():
        out = dict({"$schema": "./walls.schema.json"}, **out)
        target = Path(path)
        try:
            (target.parent / "walls.schema.json").write_bytes(
                schema.read_bytes())
        except OSError:
            pass                      # the library is what matters
    written = _write(Path(path), out)
    return {"walls": len(entries), "path": str(written), "locale": code}


def import_library(path, locale: str | None = None) -> dict:
    """Add a user's wall types, and say what could not be read.

    A wall is imported **only if it is clean** — every role and material known,
    every thickness a skin can be, a name and a key — because what lands in the
    user's file is read on every start. Anything doubtful is skipped and
    reported with the reason.
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        entries = data.get("walls") or []
        file_locale = str(data.get("locale") or "").strip()
    elif isinstance(data, list):
        entries = data
        file_locale = ""
    else:
        raise ValueError("this file holds neither a list of walls nor an "
                         "object with a 'walls' list")

    problems: list[str] = []
    accepted = []
    legacy: dict = {}
    shipped: dict = {}
    mine: dict = {}
    for code in {file_locale, locale or ""} - {""}:
        if not (DATA / f"{code}.json").is_file():
            continue
        for entry in _document(code).get("walls") or ():
            if not isinstance(entry, dict) or not entry.get("key"):
                continue
            key = str(entry["key"])
            shipped.setdefault(key, entry)
            if entry.get("legacy"):
                legacy[key] = str(entry["legacy"])
    for entry in _user_raw().get("walls") or []:
        if not isinstance(entry, dict) or not entry.get("key"):
            continue
        key = str(entry["key"])
        mine[key] = entry
        if entry.get("legacy"):
            legacy[key] = str(entry["legacy"])

    untouched = 0
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append("an entry that is not a wall")
            continue
        code = str(entry.get("locale") or file_locale or locale or "").strip()
        if not code:
            problems.append(f"{entry.get('key') or 'a wall'}: no library says "
                            f"which country it belongs to")
            continue
        before = len(problems)
        wall = _wall(entry, code, sink=problems)
        if wall is None or len(problems) > before:
            continue
        stored = dict(entry)
        stored["locale"] = code
        # An alias belongs to the key, not to whoever types the file: importing
        # a corrected cavity wall must not lose the name a document already
        # cites it by.
        if not stored.get("legacy") and legacy.get(stored["key"]):
            stored["legacy"] = legacy[stored["key"]]
        # A wall that already says exactly this needs no copy in the user's
        # file — otherwise exporting a library to edit one wall would shadow
        # every other wall in it for good. The user's own copy is checked
        # first: importing a file one has already imported is not a change.
        known = mine.get(stored["key"]) or shipped.get(stored["key"])
        if known is not None and _same(stored, known):
            untouched += 1
            continue
        accepted.append(stored)

    current = _user_raw()
    order, by_key = [], {}
    for entry in current.get("walls") or []:
        if not isinstance(entry, dict) or not entry.get("key"):
            continue
        key = str(entry["key"])
        if key not in by_key:
            order.append(key)
        by_key[key] = entry
    added = updated = 0
    for entry in accepted:
        key = str(entry["key"])
        if key in by_key:
            updated += 1
        else:
            order.append(key)
            added += 1
        by_key[key] = entry
    if accepted:
        _write(user_path(), {
            "note": "The wall types you imported, read beside the ones the "
                    "extension ships. Remove a wall here to go back to the "
                    "shipped one; remove the file to lose them all.",
            "walls": [by_key[key] for key in order],
        })
    reset()
    return {"imported": added, "updated": updated, "unchanged": untouched,
            "skipped": len(entries) - len(accepted) - untouched,
            "locales": sorted({str(entry["locale"]) for entry in accepted}),
            "problems": problems, "path": str(user_path())}


def wall(key: str, locale: str | None = None) -> dict | None:
    """The wall with this key — or this legacy key, which is what a document
    written before the library stores in ``group.ext``."""
    wanted = str(key or "").strip()
    if not wanted:
        return None
    for code in ((_locale(locale),) if locale else languages()):
        for entry in walls(code):
            if entry["key"] == wanted or entry.get("legacy") == wanted:
                return entry
    return None


def profile_key(entry: dict) -> str:
    """The name a wall type is known by: the legacy one where a document may
    already cite it, otherwise its key."""
    return entry.get("legacy") or entry["key"]


def wall_name(entry: dict, language: str | None = None) -> str:
    return _first(entry["names"], language or entry.get("locale")) or entry["key"]


def named(entry: dict, language: str | None = None) -> dict:
    """The wall with its skins' names filled in for one language.

    The stored name is the label in the library's own language — a Dutch wall is
    named in Dutch in the document, whatever the interface is set to — and the
    panel shows the role in the language the user is working in.
    """
    code = language or entry.get("locale")
    out = dict(entry)
    out["name"] = wall_name(entry, code)
    out["skins"] = [dict(skin, name=role_label(skin["role"], code)
                         or skin.get("name") or "")
                    for skin in entry["skins"]]
    return out


def profile_walls(locale: str | None = None) -> dict:
    """The library in the shape ``profiles.WALLS`` has always had.

    ``profiles`` reads this so the panel, the tool and every stored document
    keep working while the picker is still the old combo box: same keys, same
    ``nl``/``en`` names, same ``(name, thickness, material)`` skins.
    """
    out = {}
    for entry in walls(locale):
        filled = named(entry)
        out[profile_key(entry)] = {
            "nl": _first(entry["names"], "nl"),
            "en": _first(entry["names"], FALLBACK),
            "height": DEFAULT_HEIGHT,
            "skins": [(skin["name"], skin["thickness"], skin["material"])
                      for skin in filled["skins"]],
        }
    return out


# ---- finding one -----------------------------------------------------------
def search(locale: str | None = None, query: str = "",
           language: str | None = None, kind: str | None = None) -> list[dict]:
    """The walls of one library matching ``query``, in any language.

    Searching every language is the point: a Dutch user looking for a cavity
    wall finds ``Spouwmuur`` by typing "cavity", and a German one finds it by
    typing "Ziegel".
    """
    words = " ".join(str(query or "").split()).casefold().split(" ")
    words = [word for word in words if word]
    found = []
    for entry in walls(locale):
        if kind and entry["kind"] != kind:
            continue
        haystack = " ".join([entry["key"], entry.get("legacy", ""),
                             *entry["names"].values()]).casefold()
        if all(word in haystack for word in words):
            found.append(entry)
    return found


def report(locale: str | None = None) -> dict:
    """How much of a library is there, and how much of it is signed off.

    A count, not a verdict: ten external and ten internal is the target, and a
    library that is still growing is reported rather than refused.
    """
    out = {}
    for code in ((_locale(locale),) if locale else languages()):
        entries = walls(code)
        out[code] = {
            "exterior": sum(1 for e in entries if e["kind"] == "exterior"),
            "interior": sum(1 for e in entries if e["kind"] == "interior"),
            "reviewed": sum(1 for e in entries if e["reviewed"]),
            "draft": sum(1 for e in entries if not e["reviewed"]),
        }
    return out
