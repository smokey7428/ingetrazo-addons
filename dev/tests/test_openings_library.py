#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Check the wall library: the data, the words, and the migration.

Content cannot be tested — whether ten walls are the *most used* ones in a
country is a question for a person, not for a test. What can be tested is
everything around it, and that is what this file does:

* **the files are clean**: every role and material a wall cites exists in
  ``labels.json``, every key carries its library, every skin is a thickness a
  skin can be, and loading reports no problems at all;
* **the words are complete**: every role and material a library uses has a
  label in all five languages, so no build-up can ever show a blank layer;
* **units change in one place**: millimetres in the files, metres everywhere
  else, and 300 mm of wall is 0.300 m of wall;
* **the migration is real**: a wall drawn before the library existed stores
  ``{"name": "Buitenblad"}``, and that name is recognised as ``outer_leaf`` in
  any of the five languages;
* **nothing unverified is sold as reviewed**: the two build-ups this extension
  has already shipped are ``reviewed``, everything drafted since is a draft;
* **no performance is claimed**: the fields exist and are empty.

Usage:  python3 dev/tests/test_openings_library.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app_stubs                                                    # noqa: E402

EXT = HERE.parent.parent / "extensions" / "openings"

failures: list[str] = []
checks = 0


def check(condition, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def equal(got, want, message: str) -> None:
    check(got == want, f"{message}: got {got!r}, want {want!r}")


def close(got, want, message: str, tol: float = 1e-9) -> None:
    check(abs(got - want) <= tol,
          f"{message}: got {got!r}, want {want!r} (tol {tol})")


def load(name: str):
    full = f"ingetrazo_plugin_openings.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, EXT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    setattr(sys.modules["ingetrazo_plugin_openings"], name, module)
    spec.loader.exec_module(module)
    return module


def install_package() -> None:
    package = types.ModuleType("ingetrazo_plugin_openings")
    package.__path__ = [str(EXT)]
    sys.modules["ingetrazo_plugin_openings"] = package


#: Every language the library speaks. A role without a label in one of these is
#: a layer that shows blank for somebody, so the table has to be complete.
LANGUAGES = ("nl", "en-GB", "de", "es-ES", "es-PE")


# ---- the files --------------------------------------------------------------
def test_files(library) -> None:
    library.reset()
    equal(library.problems(), [], "the library loads without a single problem")
    check("nl" in library.languages(), "the Dutch library is there")
    for code in library.languages():
        check((library.DATA / f"{code}.json").is_file(),
              f"{code} is listed because its file exists")
    equal(tuple(library.languages()),
          tuple(code for code in library.LOCALES if code in library.languages()),
          "the shipped libraries keep their declared order")
    check((library.DATA / "labels.json").is_file(), "labels.json is beside them")


def test_every_wall(library) -> None:
    """What has to be true of every wall in every library, forever."""
    for code in library.languages():
        entries = library.walls(code)
        check(bool(entries), f"{code} has walls")
        for entry in entries:
            key = entry["key"]
            check(key.startswith(code + "."),
                  f"{key}: the key names its library")
            check(entry["kind"] in ("exterior", "interior"),
                  f"{key}: is exterior or interior")
            check(1 <= len(entry["skins"]) <= library.MAX_SKINS,
                  f"{key}: {len(entry['skins'])} skins, and 1–"
                  f"{library.MAX_SKINS} is buildable")
            total = 0.0
            for index, skin in enumerate(entry["skins"]):
                total += skin["thickness"]
                check(library.MIN_SKIN <= skin["thickness"] <= library.MAX_SKIN,
                      f"{key}: skin {index + 1} is between 10 and 500 mm")
                check(bool(library.role_label(skin["role"])),
                      f"{key}: skin {index + 1} has a role we can name")
                check(bool(library.material_label(skin["material"])),
                      f"{key}: skin {index + 1} has a material we can name")
                check(library.material_density(skin["material"]) is not None,
                      f"{key}: skin {index + 1}'s material has a density")
            check(total > 0.05, f"{key}: is a wall, not a sheet "
                               f"({total * 1000:.0f} mm)")
            # The words, in every language, so nothing shows blank.
            for language in LANGUAGES:
                check(bool(library.wall_name(entry, language)),
                      f"{key}: has a name in {language}")
            check(bool(entry["source"]), f"{key}: says where it came from")
            check(bool(entry["checked"]), f"{key}: says when it was checked")


def test_labels_complete(library) -> None:
    """A role or a material used *anywhere* has a label in *every* language."""
    table = library.labels()
    used_roles, used_materials = set(), set()
    for code in library.languages():
        for entry in library.walls(code):
            for skin in entry["skins"]:
                used_roles.add(skin["role"])
                used_materials.add(skin["material"])

    for role in sorted(used_roles):
        for language in LANGUAGES:
            check(bool(library.role_label(role, language)),
                  f"role {role} is named in {language}")
    for material in sorted(used_materials):
        for language in LANGUAGES:
            check(bool(library.material_label(material, language)),
                  f"material {material} is named in {language}")
        check(library.material_density(material) is not None,
              f"material {material} can be weighed")
        check(table["materials"][material]["ifc"] is not None
              or material == "Air",
              f"material {material} names the IFC material to write")


def test_units(library) -> None:
    """Millimetres in the file, metres in the code: one boundary."""
    close(library._millimetres(100), 0.100, "100 mm is 0.100 m")
    close(library._millimetres(12), 0.012, "12 mm is 0.012 m")
    equal(library._millimetres("thick"), None, "an unreadable thickness is None")
    entry = library.wall("spouwmuur")
    close(sum(s["thickness"] for s in entry["skins"]), 0.300,
          "the cavity wall is 300 mm of wall")
    equal([round(s["thickness"], 3) for s in entry["skins"]], [0.1, 0.1, 0.1],
          "and three layers of 100 mm")


def test_language_chain(library) -> None:
    equal(library.default_language("nl"), "nl", "Dutch answers Dutch")
    equal(library.default_language("de"), "de", "German answers German")
    equal(library.default_language("es"), "es-ES",
          "the app's one Spanish answers Spain's, the base case")
    equal(library.default_language("en"), "en-GB", "English answers the UK's")
    equal(library.default_language("pt-BR"), "en-GB",
          "a language we do not speak falls back to English")
    equal(library.chain("es-PE"), ("es-PE", "es-ES", "es", "en-GB"),
          "a missing Peruvian label borrows Spain's before it borrows English")
    equal(library.chain("de"), ("de", "en-GB"), "German has one sibling: English")


def test_named_in_another_language(library) -> None:
    """A Dutch wall, read by a German: Dutch name, German layers."""
    entry = library.wall("spouwmuur")
    equal(library.wall_name(entry, "de"), "Zweischalige Wand 100-100-100",
          "the wall keeps its Dutch name")
    equal([s["name"] for s in library.named(entry, "de")["skins"]],
          ["Außenschale", "Dämmung", "Innenschale"],
          "and its layers are named in German")
    equal([s["name"] for s in library.named(entry, "es-PE")["skins"]],
          ["Muro exterior", "Aislamiento", "Muro interior"],
          "or in the Spanish of Peru")
    equal([s["name"] for s in library.named(entry)["skins"]],
          ["Buitenblad", "Isolatie", "Binnenblad"],
          "and with no language asked for, in the library's own")


def test_migration(library, walls) -> None:
    """A wall drawn before the library existed keeps working."""
    equal(library.role_for("Buitenblad"), "outer_leaf", "Dutch, recognised")
    equal(library.role_for("  buitenblad "), "outer_leaf",
          "and recognised through case and spacing")
    equal(library.role_for("Außenschale"), "outer_leaf", "German, recognised")
    equal(library.role_for("hoja exterior"), "outer_leaf", "Spanish, recognised")
    equal(library.role_for("Nonsense"), None, "a name we do not know stays None")
    equal(library.role_for(""), None, "and so does an empty one")

    old = walls.normalize({"type": "spouwmuur", "height": 2.7,
                           "skins": [{"name": "Buitenblad", "thickness": 0.1,
                                      "material": "Brick"},
                                     {"name": "Mijn laag", "thickness": 0.05,
                                      "material": "Brick"}]})
    equal([s["role"] for s in old["skins"]], ["outer_leaf", ""],
          "a stored name recovers its role; a typed one stays free text")
    equal([s["name"] for s in old["skins"]], ["Buitenblad", "Mijn laag"],
          "and the names the document holds are untouched")


def test_reviewed(library) -> None:
    """Nothing drafted from a standard is sold as signed off."""
    reviewed = {e["legacy"] or e["key"] for e in library.walls("nl")
                if e["reviewed"]}
    equal(reviewed, {"spouwmuur", "binnenwand"},
          "only the two build-ups that already shipped are reviewed")
    for entry in library.walls("nl"):
        check(entry["performance"] == {"rc": None, "u": None,
                                       "value_source": None,
                                       "value_checked": None},
              f"{entry['key']}: claims no performance, only has the fields")


def test_report(library) -> None:
    counts = library.report("nl")["nl"]
    equal(counts["exterior"] + counts["interior"], len(library.walls("nl")),
          "every wall is counted once")
    equal(counts["draft"] + counts["reviewed"], len(library.walls("nl")),
          "and is either a draft or signed off")
    check(counts["exterior"] >= 1 and counts["interior"] >= 1,
          "both halves of the library have something in them")


def test_search(library) -> None:
    equal(len(library.search("nl", "spouwmuur")), 2,
          "\"spouwmuur\" finds both cavity walls")
    found = library.search("nl", "cavity")
    check(len(found) == 2, "and \"cavity\" finds the same two, in English")
    check(all(e["kind"] == "exterior"
              for e in library.search("nl", "", kind="exterior")),
          "a kind filter keeps to that kind")
    equal(library.search("nl", "zzz"), [], "and nothing matches nonsense")
    check(len(library.search("nl", "spouwmuur 120")) == 1,
          "two words narrow it to one")


def test_profiles_bridge(library, profiles) -> None:
    """The old shape, so the panel and every document keep working."""
    equal(tuple(profiles.WALLS)[:2], ("spouwmuur", "binnenwand"),
          "the legacy keys lead, in the order the file gives them")
    equal(profiles.WALLS["spouwmuur"]["nl"], "Spouwmuur 100-100-100",
          "and a type is named from the library")
    equal(profiles.WALLS["spouwmuur"]["skins"],
          [("Buitenblad", 0.1, "Brick"), ("Isolatie", 0.1, "Insulation"),
           ("Binnenblad", 0.1, "Block")],
          "with the skins in the shape the extension has always read")
    # The literal fallback and the file cannot drift: if the data cannot be
    # read, the panel offers these two instead.
    for key, entry in profiles._FALLBACK_WALLS.items():
        equal(profiles.WALLS[key]["skins"], entry["skins"],
              f"the fallback {key} is the wall in the file")
    equal(profiles.DENSITY["Brick"], 1800.0, "a material's density still says")


def test_fresh_wall(library, walls) -> None:
    """A wall made from the library carries roles, in the library's language."""
    wall = walls.defaults()
    equal(wall["type"], "spouwmuur", "the cavity wall is still the first")
    equal([s["role"] for s in wall["skins"]],
          ["outer_leaf", "insulation", "inner_leaf"], "every skin says its role")
    equal([s["name"] for s in wall["skins"]],
          ["Buitenblad", "Isolatie", "Binnenblad"],
          "and is named in Dutch, the library's own language")
    german = walls.defaults("spouwmuur", language="de")
    equal([s["name"] for s in german["skins"]],
          ["Außenschale", "Dämmung", "Innenschale"],
          "or in whichever language the wall is made in")
    other = walls.defaults("nl.kalkzandsteen.100")
    equal(other["skins"][0]["material"], "LimeSandStone",
          "a wall beyond the first two builds too")
    close(walls.total_thickness(other), 0.100, "at its own thickness")


def test_broken_file_is_reported(library) -> None:
    """A bad entry is a problem to report, never an exception in a panel."""
    library.reset()
    library.labels()                      # the roles must be known first
    before = len(library.problems())

    skip = library._wall({"kind": "diagonal", "skins": [
        {"role": "unicorn", "thickness": 50, "material": "Cheese"}]}, "nl")
    equal(skip, None, "a wall with no key is skipped")
    check("key" in " ".join(library.problems()), "and the report says so")

    odd = library._wall({"key": "nl.odd.1", "kind": "diagonal",
                         "names": {"nl": "Raar"},
                         "skins": [{"role": "unicorn", "thickness": 50,
                                    "material": "Cheese"}]}, "nl")
    check(odd is not None, "a wall with a key but nonsense in it still builds")
    said = " ".join(library.problems())
    for word in ("kind", "unicorn", "Cheese"):
        check(word in said, f"and the report names what was wrong: {word!r}")
    equal(odd["kind"], "exterior", "a bad kind lands on exterior, not on nothing")
    check(len(library.problems()) > before, "the report grew")

    thin = library._wall({"key": "nl.thin.1", "kind": "interior",
                          "names": {"nl": "Dun"}, "skins": [
                              {"role": "finish", "thickness": 1,
                               "material": "Gypsum"}]}, "nl")
    equal(thin, None, "a skin thinner than a skin may be is refused")
    check("outside" in " ".join(library.problems()),
          "and says it was outside the range")

    library.reset()
    equal(library.problems(), [], "and a reset forgets all of it")


# ---- the run ----------------------------------------------------------------
def main() -> int:
    install_package()
    library = load("library")
    profiles = load("profiles")
    walls = load("walls")

    test_files(library)
    test_every_wall(library)
    test_labels_complete(library)
    test_units(library)
    test_language_chain(library)
    test_named_in_another_language(library)
    test_migration(library, walls)
    test_reviewed(library)
    test_report(library)
    test_search(library)
    test_profiles_bridge(library, profiles)
    test_fresh_wall(library, walls)
    test_broken_file_is_reported(library)

    if failures:
        for failure in failures:
            print(f"!! {failure}")
        print(f"{len(failures)} of {checks} checks failed.")
        return 1
    print(f"openings library: ok ({checks} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
