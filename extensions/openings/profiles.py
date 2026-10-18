# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""Dutch standard sizes and timber sections, in one place.

Everything this extension ships as a default comes from here, so **adding a
type later is a line of data, not a change to the geometry**. When the door and
window types are expanded, they are expanded here, against Dutch practice.

Sizes are metres. The two numbers that matter are the *section* — the width you
see in elevation and the depth into the wall — and the *opening*, which is what
``width`` and ``height`` mean everywhere else in the extension.

A frame is that section deep, not as deep as the wall: a kozijn is 114 mm of
timber set in the wall, and what is left of the reveal is finished by somebody
else. ``frame_depth`` of 0 means "fill the whole reveal", for a lining that is
meant to close it.

Sections
    ``kozijn`` is kozijnhout 67 × 114 mm: the frame a window or a door is
    built from. ``raam`` is raamhout 54 × 67 mm: the section of a sash that
    opens.

Glazing
    ``hr++`` at 20 mm is the double glazing these defaults assume; ``enkel``
    and ``triple`` are here so a later type can name one.

Types
    A window's opening is the frame's outside, which is what a kozijn is
    ordered by, so 1000 × 1500 mm is a 1000 × 1500 frame. A door is ordered by
    its **leaf**, so the opening is derived: a 930 mm leaf in a 67 mm frame
    wants a 1064 mm opening, and a 2015 mm leaf wants 2082 mm — the leaf plus
    the head member, a door having no bottom member.

    If your office keeps its own list, change it here and every default, and
    the preset row in the panel, follows.
"""
from __future__ import annotations

MM = 0.001

#: Timber sections, in metres: ``(width in elevation, depth into the wall)``.
#: Kozijnhout 67 × 114 is the one section both a window and a door are framed
#: with; a sash is raamhout 54 × 67.
SECTIONS = {
    "kozijn": (67 * MM, 114 * MM),        # kozijnhout 67 × 114
    "raam": (54 * MM, 67 * MM),           # raamhout 54 × 67, an opening sash
}

#: Bulk density of the materials a wall is built from, kg/m³ — what a builder
#: orders in tonnes and what a take-off bills in kilos. A rough, honest figure
#: per material, not a structural value.
DENSITY = {
    "Brick": 1800.0,
    "Insulation": 30.0,
    "Block": 700.0,
    "Concrete": 2400.0,
    "Timber": 500.0,
    "Steel": 7850.0,
}

#: Glazing thicknesses, by name.
GLASS = {
    "enkel": 4 * MM,
    "hr++": 20 * MM,
    "triple": 28 * MM,
}

#: Wall build-ups, the way Dutch practice builds them. A skin is
#: ``(name, thickness, material)``, listed from the outside in; the wall is
#: centred on the line it is drawn along, so the list reads left to right as you
#: walk the path. Adding a build-up later is a line of data.
WALLS = {
    "spouwmuur": {
        "nl": "Spouwmuur",
        "en": "Cavity wall",
        "height": 2700 * MM,
        "skins": [
            ("Buitenblad", 100 * MM, "Brick"),
            ("Isolatie", 100 * MM, "Insulation"),
            ("Binnenblad", 100 * MM, "Block"),
        ],
    },
    "binnenwand": {
        "nl": "Binnenwand",
        "en": "Inner wall",
        "height": 2700 * MM,
        "skins": [
            ("Binnenblad", 100 * MM, "Block"),
        ],
    },
}

#: The window types. ``sash`` names the section of the part that opens;
#: ``None`` is a fixed window, which has none.
WINDOWS = {
    "fixed": {
        "nl": "Vast raam",
        "en": "Fixed window",
        "width": 1000 * MM,
        "height": 1500 * MM,
        "sill": 900 * MM,
        "section": "kozijn",
        "sash": None,
        "glass": "hr++",
        "symbol": False,
        "open_angle": 0.0,
        "handing": "left",
        "swing": "in",
    },
    "swing": {
        "nl": "Draairaam",
        "en": "Side-hung opening window",
        "width": 1000 * MM,
        "height": 1500 * MM,
        "sill": 900 * MM,
        "section": "kozijn",
        "sash": "raam",
        "glass": "hr++",
        "symbol": True,
        "open_angle": 90.0,
        "handing": "left",
        "swing": "in",
    },
}

#: The door types. A door is ordered by its leaf, so the opening is derived.
DOORS = {
    "hinged": {
        "nl": "Stompe deur",
        "en": "Single hinged door",
        "leaf_width": 930 * MM,           # a standard binnendeur
        "leaf_height": 2015 * MM,
        "section": "kozijn",
        "glass": None,
        "angle": 90.0,
        "handing": "left",
        "swing": "in",
        "threshold": 0.0,
        "handle": 1050 * MM,
    },
}

#: The leaf sizes a binnendeur is stocked in, for a preset row later.
DOOR_LEAF_WIDTHS = tuple(w * MM for w in (630, 730, 830, 930, 1030))
DOOR_LEAF_HEIGHTS = tuple(h * MM for h in (2015, 2115, 2315))


def section(name: str) -> tuple[float, float]:
    """``(width, depth)`` of a named section, or a kozijn if unknown."""
    return SECTIONS.get(name, SECTIONS["kozijn"])


def glass_thickness(name: str | None) -> float:
    """The glazing a type asks for; 0 for a type that has none."""
    if name is None:
        return 0.0
    return GLASS.get(name, GLASS["hr++"])


def types(kind: str) -> dict:
    """The catalogue a kind draws its defaults from."""
    if kind == "wall":
        return WALLS
    return WINDOWS if kind == "window" else DOORS


def names(kind: str) -> tuple[str, ...]:
    """The type names of a kind, in catalogue order."""
    return tuple(types(kind))


def default_type(kind: str) -> str:
    return names(kind)[0]


def label(kind: str, name: str) -> str:
    """What a type is called, in Dutch and in English — both, so the panel
    reads the same whoever is looking at it."""
    entry = types(kind).get(name) or {}
    dutch, english = entry.get("nl", name), entry.get("en", name)
    return f"{dutch} · {english}" if dutch != english else english


def defaults(kind: str, name: str) -> dict:
    """Every parameter a fresh opening of this kind and type starts with.

    For a door the opening is computed from the **leaf**, which is how a door
    is ordered and the one place the two kinds differ in how they are read.
    """
    entry = types(kind).get(name) or types(kind)[default_type(kind)]
    width, depth = section(entry.get("section", "kozijn"))

    if kind == "window":
        sash = entry.get("sash")
        sash_w, sash_d = section(sash) if sash else (0.0, 0.0)
        return {
            "kind": "window",
            "type": name,
            "width": entry["width"],
            "height": entry["height"],
            "sill": entry.get("sill", 0.0),
            "handing": entry.get("handing", "left"),
            "swing": entry.get("swing", "in"),
            "open_angle": entry.get("open_angle", 0.0),
            "frame_w": width,
            "frame_h": width,
            "frame_b": width,
            "frame_depth": depth,
            "sash_w": sash_w,
            "sash_d": sash_d,
            "glass_t": glass_thickness(entry.get("glass")),
            "leaf_t": 0.0,
            "threshold": 0.0,
            "handle": 0.0,
            "handle_len": 0.0,
            "symbol": bool(entry.get("symbol")),
            "symbol_z": 0.0,
            "frame_mat": "Window frame",
            "leaf_mat": "Window sash",
            "glass_mat": "Window glass",
        }

    leaf_w = entry.get("leaf_width", 930 * MM)
    leaf_h = entry.get("leaf_height", 2015 * MM)
    return {
        "kind": "door",
        "type": name,
        "width": leaf_w + 2.0 * width,        # the leaf plus both jambs
        "height": leaf_h + width,             # the leaf plus the head member
        "sill": 0.0,
        "handing": entry.get("handing", "left"),
        "swing": entry.get("swing", "in"),
        "open_angle": entry.get("angle", 90.0),
        "frame_w": width,
        "frame_h": width,
        "frame_b": 0.0,                       # a door has no bottom member
        "frame_depth": depth,                 # the section, not the whole wall
        "sash_w": 0.0,
        "sash_d": 0.0,
        "glass_t": 0.0,
        "leaf_t": 42 * MM,
        "threshold": entry.get("threshold", 0.0),
        "handle": entry.get("handle", 1050 * MM),
        "handle_len": 130 * MM,
        "symbol": True,
        "symbol_z": 0.0,
        "frame_mat": "Door frame",
        "leaf_mat": "Door leaf",
        "glass_mat": "Window glass",
    }
