# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The parameters of one opening, and what each one means.

Pure data: no Qt, no scene, no imports from the application. Everything an
opening is made of is decided here, so the geometry, the panel and the tests
all read the same definitions.

A door and a window are the **same object with different numbers**:

* both are a frame lining an opening, made of a **section** — the width you see
  in elevation (``frame_w``/``frame_h``/``frame_b``) and the depth into the
  wall (``frame_depth``);
* both may have a **part that moves** — a door's leaf, or a window's sash —
  which hangs on a hinge at one side and opens by ``open_angle``;
* both may be **glazed** (``glass_t``), a door usually not and a window always;
* a window stands on a ``sill``; a door stands on the floor.

The defaults, and the sections they use, come from :mod:`openings.profiles` —
Dutch standard sizes, in one place.

An instance keeps its parameters in ``group.ext[KEY]`` — the extension API's
slot for a group's own parameters, which survives copying, saving and opening.
"""
from __future__ import annotations

import math

from . import profiles

#: This extension's key in ``group.ext``. The extension's file stem.
KEY = "openings"

#: What the two kinds are called, and the sides.
KINDS = ("door", "window")
HANDING = ("left", "right")
SWING = ("in", "out")

#: Bounds that keep an opening an opening: metres (and degrees).
LIMITS = {
    "width": (0.30, 6.00),
    "height": (0.30, 6.00),
    "sill": (0.0, 4.00),
    "open_angle": (0.0, 179.0),
    "leaf_t": (0.0, 0.200),
    "frame_w": (0.0, 0.400),
    "frame_h": (0.0, 0.400),
    "frame_b": (0.0, 0.400),
    "frame_depth": (0.0, 0.600),
    "sash_w": (0.0, 0.200),
    "sash_d": (0.0, 0.200),
    "glass_t": (0.0, 0.060),
    "threshold": (0.0, 0.200),
    "handle": (0.0, 2.50),
    "handle_len": (0.0, 0.400),
    "symbol_z": (-1.0, 3.0),
}

_NUMBERS = tuple(LIMITS)

#: The layer an opening's own geometry goes on when the wall carries none, and
#: the one layer the plan symbols share — shared so that ONE layer hides every
#: symbol in a view that is not a plan.
LAYERS = {"door": "Doors", "window": "Windows"}
SYMBOL_LAYER = "Openings — plan"


def defaults(kind: str = "door", name: str | None = None) -> dict:
    """A fresh opening of ``kind``, of its first type unless one is named."""
    kind = kind if kind in KINDS else "door"
    return profiles.defaults(kind, name or profiles.default_type(kind))


def normalize(raw: dict | None) -> dict:
    """``raw`` as a complete, in-range, JSON-safe parameter set.

    Tolerant on purpose: parameters come from a saved document written by an
    older version, from a panel, and from a text box. Anything unreadable falls
    back to the default for its kind and type rather than raising — an opening
    that cannot be rebuilt because one number went bad is worse than one at 90°.

    Naming a **kind or type** alone is enough to get that type's defaults, which
    is how the panel switches between them.
    """
    raw = dict(raw or {})
    kind = raw.get("kind") if raw.get("kind") in KINDS else "door"
    name = raw.get("type") if raw.get("type") in profiles.names(kind) else None
    base = profiles.defaults(kind, name or profiles.default_type(kind))
    out = dict(base)
    name = out["type"]

    for key, value in raw.items():
        if key in out:
            out[key] = value
    out["kind"], out["type"] = kind, name

    for key in _NUMBERS:
        low, high = LIMITS[key]
        # The fallback is the *catalogue's* value, never whatever came in: an
        # unreadable field has to land on the standard, not on itself.
        out[key] = _number(out.get(key), base[key], low, high)

    out["handing"] = _choice(out.get("handing"), HANDING, "left")
    out["swing"] = _choice(out.get("swing"), SWING, "in")
    out["symbol"] = bool(out.get("symbol"))
    for key in ("frame_mat", "leaf_mat", "glass_mat"):
        text = str(out.get(key) or "").strip()
        out[key] = text or "Material"
    return out


def _number(raw, fallback: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value):
        return fallback
    return min(max(value, low), high)


def _choice(raw, allowed, fallback: str) -> str:
    text = str(raw or "").strip().lower()
    return text if text in allowed else fallback


# ---- what the shape depends on ---------------------------------------------
def is_window(p: dict) -> bool:
    return p.get("kind") == "window"


def moves(p: dict) -> bool:
    """Whether anything opens: a door always, a window only when it has a
    sash."""
    if is_window(p):
        return p["sash_w"] > 0.0 and p["sash_d"] > 0.0
    return p["leaf_t"] > 0.0


def glazed(p: dict) -> bool:
    return p["glass_t"] > 0.0


def frame_depth(p: dict, wall_depth: float) -> float:
    """How deep the frame section runs into the wall.

    ``frame_depth`` of 0 means "follow the wall" — which is what a door lining
    does, and what the door did before windows arrived with a real section.
    """
    depth = max(float(wall_depth), 0.02)
    if p["frame_depth"] <= 0.0:
        return depth
    return min(p["frame_depth"], depth)


def layer(p: dict) -> str:
    return LAYERS.get(p.get("kind"), LAYERS["door"])


# ---- the hinge --------------------------------------------------------------
def leaf_direction(p: dict) -> tuple[int, int]:
    """``(hangs_left, opens_away)`` as signs, from the naming in the catalogue.

    ``hangs_left``: the free edge is at larger x. ``opens_away``: the panel
    swings towards +y, away from the face that was clicked.
    """
    hangs_left = 1 if p["handing"] == "left" else -1
    opens_away = 1 if p["swing"] == "in" else -1
    return hangs_left, opens_away


def swing_angle(p: dict) -> float:
    """The signed rotation of the moving panel about the hinge, in radians.

    Positive rotates the free edge towards +y. A panel hinged on the right
    reaches -x, so the same rotation moves it the other way — hence the flip.
    """
    if not moves(p):
        return 0.0
    hangs_left, opens_away = leaf_direction(p)
    return math.radians(p["open_angle"]) * hangs_left * opens_away


def validate(p: dict) -> list[str]:
    """What is wrong with these parameters, in plain words.

    Only combinations a user can actually type: the caller has already been
    through :func:`normalize`.
    """
    problems: list[str] = []
    clear_w = p["width"] - 2.0 * p["frame_w"]
    clear_h = p["height"] - p["frame_h"] - p["frame_b"]
    if clear_w < 0.20:
        problems.append("The frame leaves less than 20 cm of clear opening — "
                        "narrow the section or widen the opening.")
    if clear_h < 0.20:
        problems.append("The head and bottom members leave less than 20 cm of "
                        "clear opening — lower the section or raise the "
                        "opening.")

    if is_window(p) and p["sash_w"] > 0.0:
        inner_w = clear_w - 2.0 * p["sash_w"]
        inner_h = clear_h - 2.0 * p["sash_w"]
        if inner_w < 0.10 or inner_h < 0.10:
            problems.append("The sash leaves no room for glass inside the "
                            "frame — narrow the sash section or widen the "
                            "window.")
        elif glazed(p) and p["glass_t"] > p["sash_d"] - 0.01:
            problems.append("The glass is thicker than the sash is deep.")
    elif glazed(p) and p["glass_t"] > frame_depth(p, 0.20) - 0.01:
        problems.append("The glass is thicker than the frame is deep.")

    if not is_window(p):
        if p["leaf_t"] > clear_w * 0.5:
            problems.append("The leaf is too thick for an opening this narrow.")
        if p["handle"] and not (0.20 <= p["handle"] <= clear_h + p["frame_b"]
                                - 0.05):
            problems.append("The handle falls outside the leaf — put it "
                            "between 20 cm and the head of the door.")
        if p["threshold"] and p["threshold"] >= p["height"] * 0.5:
            problems.append("That is not a threshold, that is a wall.")
    return problems


def describe(p: dict) -> str:
    """One line naming the opening, for a list, a schedule or a tool tip."""
    size = f"{p['width'] * 1000:.0f} × {p['height'] * 1000:.0f} mm"
    if is_window(p):
        opening = "opens" if moves(p) else "fixed"
        return f"{size} · {opening}"
    return f"{size} · {p['handing']}-hand · opens {p['swing']}"
