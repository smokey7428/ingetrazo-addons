# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The take-off: what the model is made of, wall by wall, skin by skin.

IngeTrazo's own BIM panel measures a tagged object by asking whether its face
set is closed on its own. A wall is a **stack of solids** — three skins, and a
skin cut into blocks by its openings — so that question has no useful answer for
one, and the panel shows a dash.

This reads the model the way a builder prices it instead: m² of brick, m² of
insulation, m³ of block, and the kilos that follow from the material. A wall
contributes one row per skin, and every skin's volume is *measured* from the
geometry the wall actually regenerated — not from a formula that could drift
away from it.

Pure data: no Qt. The panel and the CSV both read these rows.
"""
from __future__ import annotations

from . import object as object_mod
from . import params as params_mod
from . import profiles
from . import wall_object as wall_obj
from . import walls


def rows(scene) -> dict:
    """``{"walls": [...], "openings": [...], "totals": {...}}`` for the document.

    A wall row is one **skin**: where it belongs, what it is made of, its face
    area, its volume and its mass. An opening row is one door or window: what it
    is and how big, because that is what a schedule lists them by.
    """
    wall_rows: list = []
    opening_rows: list = []
    totals = {"area": 0.0, "volume": 0.0, "mass": 0.0}

    for group in list(scene.groups):
        wall = wall_obj.data_of(group)
        if wall is not None:
            values = wall_obj.wall_params(group)
            for skin in wall_obj.quantities(values):
                wall_rows.append({
                    "wall": group.name,
                    "part": skin["name"],
                    "material": skin["material"],
                    "area": skin["area"],
                    "volume": skin["volume"],
                    "mass": skin["mass"],
                })
                totals["area"] += skin["area"]
                totals["volume"] += skin["volume"]
                totals["mass"] += skin["mass"] or 0.0
            continue

        opening = object_mod.data_of(group)
        if opening is not None:
            values = object_mod.opening_params(group)
            opening_rows.append({
                "name": group.name,
                "kind": "window" if params_mod.is_window(values) else "door",
                "type": profiles.label(values["kind"], values["type"]),
                "width": values["width"],
                "height": values["height"],
                "sill": values["sill"],
                "opens": params_mod.moves(values),
            })

    return {"walls": wall_rows, "openings": opening_rows, "totals": totals}


def summary(data: dict) -> str:
    """One line for the top of a panel: what the model comes to."""
    totals = data.get("totals") or {}
    skins = len(data.get("walls") or ())
    openings = len(data.get("openings") or ())
    mass = totals.get("mass") or 0.0
    return (f"{totals.get('area', 0.0):.1f} m² · "
            f"{totals.get('volume', 0.0):.2f} m³ · {mass / 1000:.1f} t "
            f"— {skins} skin(s), {openings} opening(s)")


def wall_lines(data: dict) -> str:
    """The walls as plain text: one line per skin, totalled per wall."""
    lines: list = []
    current = None
    running = 0.0
    for row in data.get("walls") or ():
        if row["wall"] != current:
            if current is not None:
                lines.append(f"  {'':<12} {'':<10} {running:6.2f} m²")
            lines.append(f"{row['wall']}")
            current, running = row["wall"], 0.0
        running += row["area"]
        mass = f" · {row['mass']:.0f} kg" if row["mass"] else ""
        lines.append(f"  {row['part']:<12} {row['material']:<10} "
                     f"{row['area']:6.2f} m² · {row['volume']:.3f} m³{mass}")
    if current is not None:
        lines.append(f"  {'':<12} {'':<10} {running:6.2f} m²")
    return "\n".join(lines) or "—"


def opening_lines(data: dict) -> str:
    """The doors and windows as plain text — a schedule, by kind."""
    lines: list = []
    for kind in ("door", "window"):
        chosen = [row for row in data.get("openings") or ()
                  if row["kind"] == kind]
        if not chosen:
            continue
        lines.append(f"{kind.capitalize()}s ({len(chosen)})")
        for row in chosen:
            size = (f"{row['width'] * 1000:.0f} × {row['height'] * 1000:.0f}"
                    f" mm")
            extra = f" · sill {row['sill'] * 1000:.0f}" if row["sill"] else ""
            extra += " · opens" if row["opens"] else " · fixed"
            lines.append(f"  {row['name']:<10} {size:<16} "
                         f"{row['type']}{extra}")
    return "\n".join(lines) or "—"


def csv(data: dict) -> str:
    """The take-off as CSV — the table a spreadsheet or a budget reads.

    One row per thing with a quantity: a wall's skin, or one door or window.
    Every number is the one the panel shows, because both read these rows.
    """
    lines = ["kind,element,part,material,area_m2,volume_m3,mass_kg,"
             "width_m,height_m,sill_m"]
    for row in data.get("walls") or ():
        mass = "" if row["mass"] is None else f"{row['mass']:.2f}"
        lines.append(f"wall,\"{_q(row['wall'])}\",\"{_q(row['part'])}\","
                     f"\"{_q(row['material'])}\",{row['area']:.4f},"
                     f"{row['volume']:.4f},{mass},,,")
    for row in data.get("openings") or ():
        lines.append(f"{row['kind']},\"{_q(row['name'])}\",\"{_q(row['type'])}\","
                     f",,1,,{row['width']:.4f},{row['height']:.4f},"
                     f"{row['sill']:.4f}")
    return "\n".join(lines) + "\n"


def _q(text) -> str:
    return str(text).replace('"', "'")
