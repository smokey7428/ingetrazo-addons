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

#: What a skin may be, in metres. Below 10 mm it is a line rather than a layer,
#: which is why a vapour barrier is not a skin (see the timber wall's note).
MIN_SKIN, MAX_SKIN = 0.010, 0.500

#: Skins in one wall, as much as the geometry will take.
MAX_SKINS = 8

_KINDS = ("exterior", "interior")

_cache: dict = {}
_problems: list[str] = []


# ---- reading ---------------------------------------------------------------
def _remember(problem: str) -> None:
    if problem not in _problems:
        _problems.append(problem)


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
    try:
        with path.open("r", encoding="utf-8") as handle:
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
    """Which libraries are actually present, in the order to offer them."""
    if "languages" not in _cache:
        found = {path.stem for path in DATA.glob("*.json")} - {"labels"}
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
def walls(locale: str | None = None) -> tuple[dict, ...]:
    """One library, every wall, thicknesses in metres."""
    code = _locale(locale)
    slot = ("walls", code)
    if slot not in _cache:
        raw = _read(DATA / f"{code}.json", {})
        loaded = []
        for entry in raw.get("walls") or ():
            wall = _wall(entry, code) if isinstance(entry, dict) else None
            if wall is not None:
                loaded.append(wall)
        if not loaded:
            _remember(f"{code}.json has no usable walls")
        _cache[slot] = tuple(loaded)
    return _cache[slot]


def _wall(entry: dict, locale: str) -> dict | None:
    """One entry from a file, checked enough to be trusted by the geometry."""
    key = str(entry.get("key") or "").strip()
    if not key.startswith(locale + "."):
        _remember(f"{locale}.json: a wall's key should start with "
                  f"{locale!r}, got {key!r}")
    if not key:
        _remember(f"{locale}.json: a wall with no key was skipped")
        return None

    kind = entry.get("kind")
    if kind not in _KINDS:
        _remember(f"{key}: kind should be exterior or interior, got {kind!r}")
        kind = _KINDS[0]

    names = {str(code): str(value) for code, value in
             (entry.get("names") or entry.get("name") or {}).items()}
    if not names:
        _remember(f"{key}: no name in any language")

    known_roles = labels()["roles"]
    known_materials = labels()["materials"]
    skins = []
    for index, skin in enumerate(entry.get("skins") or ()):
        if not isinstance(skin, dict):
            continue
        thickness = _millimetres(skin.get("thickness"))
        if thickness is None or thickness <= 0:
            _remember(f"{key}: skin {index + 1} has no readable thickness")
            continue
        if not MIN_SKIN <= thickness <= MAX_SKIN:
            _remember(f"{key}: skin {index + 1} is {thickness * 1000:.0f} mm, "
                      f"outside {MIN_SKIN * 1000:.0f}–{MAX_SKIN * 1000:.0f} mm")
            continue
        role = str(skin.get("role") or "").strip()
        if role not in known_roles:
            _remember(f"{key}: skin {index + 1} has role {role!r}, which is not "
                      f"in labels.json")
        material = str(skin.get("material") or "").strip()
        if material not in known_materials:
            _remember(f"{key}: skin {index + 1} has material {material!r}, "
                      f"which is not in labels.json")
        skins.append({"role": role, "name": "", "thickness": thickness,
                      "material": material})
    if not skins:
        _remember(f"{key}: no usable skins, so the wall was skipped")
        return None
    if len(skins) > MAX_SKINS:
        _remember(f"{key}: {len(skins)} skins, and {MAX_SKINS} is the most the "
                  f"geometry builds")

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
        "reviewed": bool(entry.get("reviewed")),
        "note": str(entry.get("note") or "").strip(),
        "performance": {"rc": performance.get("rc"),
                        "u": performance.get("u"),
                        "value_source": performance.get("value_source"),
                        "value_checked": performance.get("value_checked")},
    }


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
