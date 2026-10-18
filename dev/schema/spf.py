# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""A reader for STEP Physical Files — the ``.ifc`` text format (ISO 10303-21).

Enough of it for the property-set template files buildingSMART publishes, and
for the header, which is all the generator needs. It is deliberately not a
general IFC reader: geometry, inverse attributes and units are somebody
else's problem here.

The grammar of a ``DATA`` section is small::

    #12= IFCWALL('guid',$,'Wall',$,.STANDARD.,(0.,0.,0.),#9,#11,'tag',$);

so a value is one of ``$`` (unset), ``*`` (derived), ``#n`` (a reference),
``'text'``, ``.ENUM.``, a number, a ``(…)`` list, or ``NAME(…)`` — a typed
value such as ``IFCLABEL('GPS')``.

Strings carry the encoding escapes IFC uses for anything outside ASCII:
``''`` for an apostrophe, ``\\S\\x`` for the character at code point
``ord(x) + 128``, and ``\\X\\HH`` / ``\\X2\\…\\X0\\`` for code points in hex.
They are decoded here, so callers see plain text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Ref:
    """A reference to another instance: ``#12``."""

    id: int

    def __repr__(self) -> str:                    # keeps failures readable
        return f"#{self.id}"


class EnumValue(str):
    """An enumeration literal: ``.PSET_TYPEDRIVENOVERRIDE.``.

    A ``str`` subclass so it compares equal to the bare name, while callers
    that care can still tell it apart from a quoted string.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return f".{str(self)}."


#: ``*`` — an attribute a subtype derives rather than stores.
DERIVED = object()


@dataclass
class Instance:
    type_name: str
    args: list = field(default_factory=list)

    def get(self, index: int, default=None):
        """Argument ``index``, or ``default`` when absent."""
        try:
            return self.args[index]
        except IndexError:
            return default


_ID = re.compile(r"#(\d+)")


def _decode_string(raw: str) -> str:
    """Undo IFC's string escapes. ``raw`` excludes the surrounding quotes."""
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if raw.startswith("\\X2\\", i):
            end = raw.find("\\X0\\", i)
            if end == -1:
                out.append(raw[i:])
                break
            hexes = raw[i + 4:end]
            for j in range(0, len(hexes) - 3, 4):
                out.append(chr(int(hexes[j:j + 4], 16)))
            i = end + 4
        elif raw.startswith("\\X\\", i) and i + 3 < n:
            out.append(chr(int(raw[i + 3:i + 5], 16)))
            i += 5
        elif raw.startswith("\\S\\", i) and i + 3 < n:
            out.append(chr(ord(raw[i + 3]) + 128))
            i += 4
        else:
            # Any other backslash is a literal one (\P\, \N\, …).
            out.append(ch)
            i += 1
    text = "".join(out)
    return text.replace("''", "'")


class _Scanner:
    """A cursor over the instance body, keeping track of which ``#n``
    arguments were seen so a whole file can be read in one pass."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.n = len(text)

    def skip_space(self) -> None:
        while self.pos < self.n and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def parse_value(self):
        self.skip_space()
        if self.pos >= self.n:
            return None
        ch = self.text[self.pos]

        if ch == "$":
            self.pos += 1
            return None
        if ch == "*":
            self.pos += 1
            return DERIVED
        if ch == "#":
            match = _ID.match(self.text, self.pos)
            if match:
                self.pos = match.end()
                return Ref(int(match.group(1)))
            self.pos += 1
            return None
        if ch == "'":
            return self._parse_string()
        if ch == ".":
            end = self.text.find(".", self.pos + 1)
            if end == -1:
                self.pos = self.n
                return None
            value = self.text[self.pos + 1:end]
            self.pos = end + 1
            return EnumValue(value)
        if ch == "(":
            return self._parse_list()
        if ch.isdigit() or ch in "+-" and self.text[self.pos + 1:self.pos + 2].isdigit():
            return self._parse_number()
        if ch.isalpha() or ch == "_":
            return self._parse_typed()
        self.pos += 1
        return None

    def _parse_string(self) -> str:
        self.pos += 1                                   # opening quote
        out: list[str] = []
        while self.pos < self.n:
            ch = self.text[self.pos]
            if ch == "'":
                if self.text[self.pos + 1:self.pos + 2] == "'":
                    out.append("'")
                    self.pos += 2
                    continue
                self.pos += 1
                break
            out.append(ch)
            self.pos += 1
        return _decode_string("".join(out))

    def _parse_list(self) -> tuple:
        self.pos += 1                                   # '('
        items: list = []
        while True:
            self.skip_space()
            if self.pos >= self.n:
                break
            if self.text[self.pos] == ")":
                self.pos += 1
                break
            if self.text[self.pos] == ",":
                self.pos += 1
                continue
            items.append(self.parse_value())
        return tuple(items)

    def _parse_number(self):
        start = self.pos
        while self.pos < self.n and self.text[self.pos] in "0123456789+-.eE":
            self.pos += 1
        raw = self.text[start:self.pos]
        try:
            if re.fullmatch(r"[+-]?\d+", raw):
                return int(raw)
            return float(raw)
        except ValueError:
            return None

    def _parse_typed(self):
        """``IFCLABEL('x')`` — returns the value, unwrapping the single
        argument, so ``IFCLABEL('GPS')`` and ``'GPS'`` read the same."""
        start = self.pos
        while self.pos < self.n and (self.text[self.pos].isalnum()
                                     or self.text[self.pos] in "_"):
            self.pos += 1
        name = self.text[start:self.pos]
        self.skip_space()
        if self.pos < self.n and self.text[self.pos] == "(":
            args = self._parse_list()
            return args[0] if len(args) == 1 else args
        return name


def parse(text: str) -> dict[int, Instance]:
    """Every ``#n= TYPE(…)`` instance in ``text``, keyed by its id.

    The header is read past; instances are returned whole, with nested values
    decoded into ``Ref``/``EnumValue``/``tuple``/``str``/``float``.
    """
    data_start = text.find("DATA;")
    body = text[data_start + 5:] if data_start != -1 else text
    end = body.find("ENDSEC;")
    if end != -1:
        body = body[:end]

    instances: dict[int, Instance] = {}
    scanner = _Scanner(body)
    while True:
        match = _ID.search(body, scanner.pos)
        if match is None:
            break
        scanner.pos = match.end()
        scanner.skip_space()
        if scanner.text[scanner.pos:scanner.pos + 1] != "=":
            continue
        scanner.pos += 1
        scanner.skip_space()
        start = scanner.pos
        while scanner.pos < scanner.n and (scanner.text[scanner.pos].isalnum()
                                           or scanner.text[scanner.pos] == "_"):
            scanner.pos += 1
        type_name = scanner.text[start:scanner.pos]
        scanner.skip_space()
        args: list = []
        if scanner.text[scanner.pos:scanner.pos + 1] == "(":
            args = list(scanner._parse_list())
        instances[int(match.group(1))] = Instance(type_name.upper(), args)
    return instances


def header_schema(text: str) -> str:
    """The schema name from ``FILE_SCHEMA(('IFC4'));`` — ``''`` when absent."""
    match = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", text)
    return match.group(1) if match else ""


def header_file_name(text: str) -> str:
    """The originating file name from ``FILE_NAME(…)``."""
    match = re.search(r"FILE_NAME\s*\(\s*'((?:[^']|'')*)'", text)
    return (match.group(1).replace("''", "'") if match else "")


def by_type(instances: dict[int, Instance], type_name: str) -> list[Instance]:
    wanted = type_name.upper()
    return [i for i in instances.values() if i.type_name == wanted]
