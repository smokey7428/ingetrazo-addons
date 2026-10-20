# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""A wall of our own: skins along a path, and the numbers that regenerate it.

This is the piece the openings did not have. IngeTrazo has no wall object — a
wall is faces — so an opening cut into it was topology surgery and the wall
stopped being anything in particular. Here a wall **is** an object: a path, a
list of skins, and a height, kept in ``group.ext``. Its geometry is regenerated
from those numbers, so from now on:

* editing the wall rebuilds it, openings and all;
* an opening is *data* on the wall, not a cut — which is the only way a window
  can stay a window and a wall stay a wall (the principle ``opentrace_bim``'s
  ``openings.py`` states, and the reason ours could not keep it).

A **skin** is one layer of the build-up — buitenblad, isolatie, binnenblad — as
``(name, thickness, material)``, listed from the outside in. The wall is centred
on the line it is drawn along, so the skins sit half on either side of it, the
way a wall is drawn in a plan.

Pure data: no Qt, no scene, no imports from the application.
"""
from __future__ import annotations

import math

from . import library
from . import profiles

#: The key in ``group.ext``. The same document-data namespace as the openings:
#: one extension, one key, and the two kinds told apart by ``kind``.
KEY = "openings"

#: What this object is, next to ``kind: door`` and ``kind: window``.
KIND = "wall"

KINDS = tuple(profiles.WALLS)


def kinds(locale: str | None = None) -> tuple[str, ...]:
    """Every build-up a wall can be drawn from, in the library's order.

    Asked each time rather than frozen at import, because a user can **import**
    a wall type while the app is running and expect to draw with it.
    """
    found = tuple(library.profile_key(entry) for entry in library.walls(locale))
    return found or KINDS


def known(name: str | None, locale: str | None = None) -> bool:
    """Whether a build-up of this name exists — ours, or the user's own."""
    if not name:
        return False
    if name in profiles.WALLS:
        return True
    return library.wall(name, locale) is not None


def default_type(locale: str | None = None) -> str:
    """The first build-up of the library, which is what a wall with no type and
    an unreadable one both land on."""
    found = kinds(locale)
    return found[0] if found else "spouwmuur"

#: Bounds that keep a wall a wall: metres.
LIMITS = {
    "height": (0.30, 12.00),
    "base": (-50.0, 500.0),
    "thickness": (0.010, 0.500),
}

#: How thin a skin may be before it is a line rather than a layer.
MIN_SKIN = 0.010
MAX_SKINS = 8


def defaults(name: str | None = None, language: str | None = None) -> dict:
    """A fresh wall of a named build-up, or of the first one.

    ``language`` is the language the skins are **named** in, not the language
    the panel shows them in: a Dutch build-up is stored with Dutch layer names
    in Dutch whatever the interface is set to, and the panel translates the role
    for display. Omitting it takes the library's own language.
    """
    return _from_profile(name if known(name) else default_type(), language)


def _from_profile(name: str, language: str | None = None) -> dict:
    """The build-up of a named type, as a new wall.

    The build-up itself comes from the library, so a skin carries the **role**
    it plays (``outer_leaf``) next to the name it was created with — the role is
    what survives a change of language, the name is what the document says.
    """
    entry = library.wall(name)
    if entry is not None:
        filled = library.named(entry, language)
        skins = [{"role": skin["role"], "name": skin["name"],
                  "thickness": float(skin["thickness"]),
                  "material": skin["material"]}
                 for skin in filled["skins"]]
    else:                                 # the library could not be read
        skins = [{"role": library.role_for(skin[0]) or "", "name": skin[0],
                  "thickness": float(skin[1]), "material": skin[2]}
                 for skin in profiles.WALLS[name]["skins"]]
    return {
        "kind": KIND,
        "type": name,
        "height": float(profiles.WALLS.get(name, {}).get("height",
                                                         library.DEFAULT_HEIGHT)),
        "base": 0.0,
        "path": [],                       # [(x, y), …] in plan, metres
        "skins": skins,
        "openings": [],                   # the host's own opening requests
    }


def _role(skin: dict) -> str:
    """Which role a skin plays: the one it states, or the one its name means.

    This is the migration. A wall drawn before the library existed stores
    ``{"name": "Buitenblad"}`` and no role, and ``"Buitenblad"`` is the Dutch
    label of ``outer_leaf`` — so the role is *recovered* rather than guessed at.
    A name that means nothing in any language stays free text with no role,
    which is what a skin the user typed is. An unknown role is dropped rather
    than stored: a role that is not in the table cannot be shown at all.
    """
    role = str(skin.get("role") or "").strip()
    if role and library.role_label(role):
        return role
    return library.role_for(skin.get("name")) or ""


def normalize(raw: dict | None) -> dict:
    """``raw`` as a complete, in-range, JSON-safe wall.

    Tolerant like the openings' parameters: a wall that cannot be rebuilt
    because one number went bad is worse than a wall at 2.7 m.
    """
    raw = dict(raw or {})
    name = raw.get("type") if known(raw.get("type")) else default_type()
    out = _from_profile(name)

    for key in ("height", "base"):
        low, high = LIMITS[key]
        out[key] = _number(raw.get(key), out[key], low, high)

    path = []
    for point in raw.get("path") or ():
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        path.append([x, y])
    out["path"] = path

    skins = []
    for skin in raw.get("skins") or ():
        if not isinstance(skin, dict):
            continue
        thickness = _number(skin.get("thickness"), 0.0, MIN_SKIN, 0.5)
        if thickness < MIN_SKIN:
            continue
        role = _role(skin)
        label = str(skin.get("name") or "").strip()
        if not label:
            label = library.role_label(role) or f"Skin {len(skins) + 1}"
        skins.append({
            "role": role,
            "name": label,
            "thickness": thickness,
            "material": str(skin.get("material") or "Wall").strip() or "Wall",
        })
        if len(skins) >= MAX_SKINS:
            break
    out["skins"] = skins or out["skins"]

    out["openings"] = _openings(raw.get("openings"), path, out["height"])
    return out


def _openings(raw, path, wall_height: float) -> list:
    """The hosted openings, each kept inside its segment and the wall.

    An opening is *data*: which segment, how far along it, how wide, and how far
    above the wall's base. It is normalised against the path and the height
    here, so the generator can trust every number it gets — an opening hanging
    off the end of a segment would otherwise build nonsense.
    """
    lengths = [(math.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(path,
                                                                     path[1:])]
    out = []
    for index, item in enumerate(raw or ()):
        if not isinstance(item, dict) or not lengths:
            continue
        segment = int(_number(item.get("segment"), 0.0, 0.0, len(lengths) - 1))
        length = lengths[segment]
        width = _number(item.get("width"), 0.0, 0.0, length)
        height = _number(item.get("height"), 0.0, 0.0, wall_height)
        if width < 0.02 or height < 0.02:
            continue
        # Kept a little inside the segment: an opening flush with a corner is
        # not an opening, it is the end of the wall.
        low, high = 0.01, max(length - 0.01, 0.02)
        width = min(width, high - low)
        if width < 0.02:
            continue
        start = min(max(_number(item.get("start"), 0.0, low, high - width),
                        low), max(high - width, low))
        sill = _number(item.get("sill"), 0.0, 0.0,
                       max(wall_height - height, 0.0))
        out.append({
            "id": str(item.get("id") or f"opening-{index + 1}"),
            "segment": segment,
            "start": start,
            "width": width,
            "sill": sill,
            "height": min(height, wall_height - sill),
        })
    return out


def _number(raw, fallback: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value):
        return fallback
    return min(max(value, low), high)


# ---- what the shape depends on ---------------------------------------------
def total_thickness(w: dict) -> float:
    """How thick the wall is across its skins."""
    return sum(float(skin["thickness"]) for skin in w["skins"])


def offsets(w: dict) -> list:
    """``[(skin, from, to), …]`` across the wall, centred on the path line.

    A wall is drawn along its centre, so the skins sit half on either side —
    which is what makes a plan read the way a drawing does.
    """
    half = total_thickness(w) * 0.5
    out, cursor = [], -half
    for skin in w["skins"]:
        thickness = float(skin["thickness"])
        out.append((skin, cursor, cursor + thickness))
        cursor += thickness
    return out


def length(w: dict) -> float:
    """The drawn length, along the path — not counting the mitred corners."""
    total = 0.0
    path = w["path"]
    for a, b in zip(path, path[1:]):
        total += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    return total


def describe(w: dict) -> str:
    """One line naming the wall, for a list, a schedule or a tool tip."""
    skins = len(w["skins"])
    return (f"{length(w):.2f} m · {total_thickness(w) * 1000:.0f} mm · "
            f"{w['height']:.2f} m high · {skins} skin"
            f"{'s' if skins != 1 else ''}")


def validate(w: dict, placed: bool = True) -> list[str]:
    """What is wrong with this wall, in plain words.

    ``placed=False`` is a build-up that has not been drawn yet: a wall in the
    panel waiting for the tool has no path, and asking it for one meant the
    type picker refused every change it was given.
    """
    problems: list[str] = []
    if placed and len(w["path"]) < 2:
        problems.append("A wall needs at least two points along its path.")
    if not w["skins"]:
        problems.append("A wall needs at least one skin.")
    if total_thickness(w) <= MIN_SKIN:
        problems.append("The skins add up to nothing — give at least one a "
                        "thickness.")
    thin = [skin["name"] for skin in w["skins"]
            if skin["thickness"] < MIN_SKIN]
    if thin:
        problems.append(f"Thinner than {MIN_SKIN * 1000:.0f} mm: "
                        f"{', '.join(thin)}.")
    if len(w["skins"]) >= MAX_SKINS:
        problems.append(f"That is {MAX_SKINS} skins — enough layers for one "
                        f"wall. Split it in two.")
    return problems
