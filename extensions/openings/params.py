# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The parameters of one door, and what each one means.

Pure data: no Qt, no scene, no imports from the application. Everything a door
is made of is decided here, so the geometry, the panel and the tests all read
the same definitions.

An instance keeps its parameters in ``group.ext[KEY]`` — the extension API's
slot for a group's own parameters, which survives copying, saving and opening.
Rebuilding a door means: same parameters, new geometry, where it stands now.
"""
from __future__ import annotations

import math

#: This extension's key in ``group.ext``. The extension's file stem.
KEY = "openings"

#: Sides. ``handing`` is which jamb the leaf hangs on, seen from the wall face
#: the user clicked; ``swing`` is which way the leaf opens from that face.
HANDING = ("left", "right")
SWING = ("in", "out")

#: What every door starts as.
DEFAULTS = {
    "width": 0.90,          # the opening in the wall (the hole), metres
    "height": 2.10,
    "handing": "left",      # hinge on the left of the face you clicked
    "swing": "in",          # the leaf opens away from that face
    "open_angle": 90.0,     # degrees the leaf stands open, and the arc drawn
    "leaf_t": 0.042,        # leaf thickness
    "frame_w": 0.06,        # width of the jamb lining
    "frame_h": 0.06,        # height of the head lining
    "frame_depth": 0.06,    # how far the lining lines the reveal
    "threshold": 0.0,       # 0 = none; a saddle across the opening
    "handle": 1.05,         # height of the handle; 0 = none
    "handle_len": 0.13,     # how far the handle stands out of the leaf
    "symbol": True,         # draw the swing symbol (the plan arc)
    "symbol_z": 0.0,        # height of the symbol above the floor
    "frame_mat": "Door frame",
    "leaf_mat": "Door leaf",
    #: The layer the swing symbol lives on, so a view can hide it: the arc is
    #: a plan convention, and in 3D or in an elevation it is in the way.
    "symbol_layer": "Doors — plan",
}

#: Which layer a door's own geometry goes on when the wall it is cut into
#: carries none (so Doors can be hidden without hiding the walls).
DEFAULT_LAYER = "Doors"

#: Bounds that keep a door a door: metres.
LIMITS = {
    "width": (0.30, 4.00),
    "height": (1.20, 4.00),
    "open_angle": (0.0, 179.0),
    "leaf_t": (0.020, 0.200),
    "frame_w": (0.0, 0.40),
    "frame_h": (0.0, 0.40),
    "frame_depth": (0.010, 0.60),
    "threshold": (0.0, 0.20),
    "handle": (0.0, 2.50),
    "handle_len": (0.0, 0.40),
    "symbol_z": (-1.0, 3.0),
}

_NUMBERS = tuple(k for k, (lo, hi) in LIMITS.items())


def defaults() -> dict:
    """A fresh copy of the defaults, safe to change."""
    return dict(DEFAULTS)


def _number(raw, fallback: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value):
        return fallback
    return min(max(value, low), high)


def normalize(raw: dict | None) -> dict:
    """``raw`` as a complete, in-range, JSON-safe parameter set.

    Tolerant on purpose: parameters come from a saved document written by an
    older version, from a dialog, and from a text field. Anything unreadable
    falls back to its default rather than raising — a door that cannot be
    rebuilt because one number went bad is worse than a door at 90°.
    """
    out = dict(DEFAULTS)
    for key, value in (raw or {}).items():
        if key in DEFAULTS:
            out[key] = value

    for key in _NUMBERS:
        low, high = LIMITS[key]
        out[key] = _number(out.get(key), DEFAULTS[key], low, high)

    out["handing"] = (str(out.get("handing", "")).strip().lower()
                      if str(out.get("handing", "")).strip().lower()
                      in HANDING else DEFAULTS["handing"])
    out["swing"] = (str(out.get("swing", "")).strip().lower()
                    if str(out.get("swing", "")).strip().lower() in SWING
                    else DEFAULTS["swing"])
    out["symbol"] = bool(out.get("symbol", DEFAULTS["symbol"]))
    for key in ("frame_mat", "leaf_mat", "symbol_layer"):
        text = str(out.get(key) or "").strip()
        out[key] = text or DEFAULTS[key]
    return out


def validate(p: dict) -> list[str]:
    """What is wrong with these parameters, in plain words.

    The caller has already been through :func:`normalize`, so this is only
    about combinations that do not add up — the ones a user can actually type.
    """
    problems: list[str] = []
    clear_w = p["width"] - 2.0 * p["frame_w"]
    clear_h = p["height"] - p["frame_h"]
    if clear_w < 0.20:
        problems.append("The jamb lining leaves less than 20 cm of clear "
                        "opening — narrow the lining or widen the door.")
    if clear_h < 0.60:
        problems.append("The head lining leaves less than 60 cm of clear "
                        "opening — lower the lining or raise the door.")
    if p["leaf_t"] > clear_w * 0.5:
        problems.append("The leaf is too thick for an opening this narrow.")
    if p["handle"] and not (0.20 <= p["handle"] <= clear_h + p["frame_h"] - 0.05):
        problems.append("The handle falls outside the leaf — put it between "
                        "20 cm and the head of the door.")
    if p["threshold"] and p["threshold"] >= p["height"] * 0.5:
        problems.append("That is not a threshold, that is a wall.")
    return problems


def leaf_direction(p: dict) -> tuple[int, int]:
    """``(hangs_left, opens_away)`` as signs, from the naming in the defaults.

    ``hangs_left``: the free edge is at larger x. ``opens_away``: the leaf
    swings towards +y, i.e. away from the face that was clicked (y = 0).
    """
    hangs_left = 1 if p["handing"] == "left" else -1
    opens_away = 1 if p["swing"] == "in" else -1
    return hangs_left, opens_away


def swing_angle(p: dict) -> float:
    """The signed rotation of the leaf about the hinge, in radians.

    Positive rotates the free edge towards +y (away from the clicked face).
    A leaf hinged on the right reaches -x, so the same rotation moves it the
    other way — hence the sign flip.
    """
    hangs_left, opens_away = leaf_direction(p)
    return math.radians(p["open_angle"]) * hangs_left * opens_away


def describe(p: dict) -> str:
    """One line naming the door, for a schedule, a list or a tool tip."""
    return (f"{p['width'] * 1000:.0f} × {p['height'] * 1000:.0f} mm · "
            f"{p['handing']}-hand · opens {p['swing']}")
