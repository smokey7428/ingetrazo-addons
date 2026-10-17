# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Eric Smook.
"""The one place that reaches into IngeTrazo's internals.

IngeTrazo 0.5.8 has **no public way for an extension to register an
interactive tool**. ``ExtensionApp`` offers panels, menus, context menus,
overlays, snap providers, pickables and file openers — and nothing else. The
roadmap's "tool registration" line means the Extensions *menu*.

The community's parametric BIM extension solves it by writing into the main
window's private collections, and says so in its own source:

    IngeTrazo 0.5.7 does not expose public tool-registration methods, so the
    private host collections are intentionally isolated in this module.

Ours are isolated here for the same reason, and :func:`unavailable` answers
*why* rather than raising: a build that moves these members should disable the
extension with a sentence the user can read, not a traceback.

Registering a tool is a different act from *building* one, which the loader
explicitly allows — ``core.extensions._builds_bare`` only auto-instantiates
plugin ``Tool`` classes that take no argument, and its comment says a tool that
needs one "is the extension's to build in its ``setup(app)``".
"""
from __future__ import annotations

import logging

log = logging.getLogger("ingetrazo.plugins")

#: What the host has to have. Each is a private member of ``MainWindow``.
_REQUIRED = ("_tools", "_tool_actions", "_tool_group", "_activate_tool")


def unavailable(app) -> str | None:
    """Why an interactive tool cannot be offered here, or ``None`` when it can.

    Checked once, at ``setup``, and again before registering: a host that has
    moved these would otherwise fail inside a click handler, where the user
    sees nothing at all.
    """
    window = getattr(app, "window", None)
    if window is None:
        return "the extension has no window"
    missing = [name for name in _REQUIRED if not hasattr(window, name)]
    if missing:
        return ("this IngeTrazo build does not expose the tool registration "
                "an interactive tool needs (" + ", ".join(missing) + ")")
    if not callable(getattr(window, "_activate_tool", None)):
        return "this IngeTrazo build's tool activation is not callable"
    return None


def register(app, key: str, tool, title: str, tip: str = "") -> bool:
    """Put ``tool`` in the host's tool list under ``key``, with its own action.

    The action makes the tool reachable the way every built-in tool is — the
    toolbar group, the ``Window ▸ …``-style lists the main window builds from
    ``_tool_actions`` — and ``_activate_tool`` marks it checked when it runs.
    False when the host is not usable, so a caller can carry on without it.
    """
    reason = unavailable(app)
    if reason:
        log.warning("openings: no interactive tool — %s", reason)
        return False
    from PySide6.QtGui import QAction

    window = app.window
    if key in window._tools:
        return True                       # already registered by a reload

    from views.shortcuts import set_tooltip

    action = QAction(title, window)
    action.setCheckable(True)
    if tip:
        set_tooltip(action, tip)
    action.triggered.connect(lambda _checked=False, k=key: activate(app, k))
    try:
        window._tool_group.addAction(action)
    except (AttributeError, RuntimeError) as exc:      # a C++ object already gone
        log.warning("openings: could not add the tool action (%s)", exc)
        return False
    window._tool_actions[key] = action
    window._tools[key] = tool
    return True


def activate(app, key: str) -> bool:
    """Make the tool active, exactly as a toolbar button would.

    ``_activate_tool`` also honours the window's tool filter, so a tool is
    refused with the app's own "not available here" message inside a workspace
    that does not allow it.
    """
    if unavailable(app):
        return False
    if key not in app.window._tools:
        return False
    app.window._activate_tool(str(key))
    return True


def action(app, key: str):
    """The ``QAction`` for a registered tool, or ``None``."""
    if unavailable(app):
        return None
    return app.window._tool_actions.get(str(key))


def is_active(app, key: str) -> bool:
    """Whether our tool is the one the viewport is running."""
    tool = app.window._tools.get(str(key)) if not unavailable(app) else None
    return tool is not None and getattr(app.viewport, "active_tool", None) is tool


def tool(app, key: str):
    """A registered tool by key, or ``None``."""
    if unavailable(app):
        return None
    return app.window._tools.get(str(key))


def select_tool(app) -> bool:
    """Switch back to the Select tool — what "press the same button again"
    means, and what a tool does when its work is done."""
    return activate(app, "select") if "select" in getattr(
        app.window, "_tools", {}) else False
