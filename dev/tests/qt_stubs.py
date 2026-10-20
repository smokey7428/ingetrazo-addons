# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 the ingetrazo-addons contributors.
"""Enough of PySide6 to run a panel's logic without Qt.

IngeTrazo's bundle ships PySide6, but it cannot be imported outside the frozen
application (shiboken's bootstrap needs PyInstaller's environment), and
installing a second PySide6 just to run tests is a heavy price. These stubs are
the cheap alternative: they let a panel be built and driven headlessly, so the
logic — what gets shown, what gets written, one undo step — is really executed
rather than reasoned about.

What they cannot tell you is whether anything *looks* right, or whether a Qt
enum, a signal name or a layout is used correctly. That still needs the app.
"""
from __future__ import annotations

import sys
import types


class Signal:
    """A Qt-like signal: connect, disconnect, emit. Slots stay simple: the
    panel's own methods take no arguments from these, except where it reads
    ``currentIndexChanged``'s index, which emit() ignores via ``*_args``."""

    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, slot=None) -> None:
        if slot is None:
            self._slots.clear()
        elif slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class QObject:
    def __init__(self, parent=None) -> None:
        self._parent = parent
        self._blocked = 0
        self._children: list = []

    def blockSignals(self, blocked: bool) -> None:
        self._blocked += 1 if blocked else -1

    def setParent(self, parent) -> None:
        self._parent = parent

    def deleteLater(self) -> None:
        pass

    def parent(self):
        return self._parent

    def window(self):
        return self


class QWidget(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.visible = True
        self.enabled = True
        self.size_policy_ignored = False
        self.minimum_width = 0
        self.tooltip = ""
        self.style = ""
        self.layout = None

    def setEnabled(self, on: bool) -> None:
        self.enabled = bool(on)

    def isEnabled(self) -> bool:
        return self.enabled

    def setDisabled(self, on: bool) -> None:
        self.enabled = not on

    def setVisible(self, on: bool) -> None:
        self.visible = bool(on)

    def isVisible(self) -> bool:
        return self.visible

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def setStyleSheet(self, css: str) -> None:
        self.style = css

    def setLayout(self, layout) -> None:
        self.layout = layout

    def setSizePolicy(self, *_a) -> None:
        pass

    def setMinimumWidth(self, width) -> None:
        self.minimum_width = int(width)

    def minimumWidth(self) -> int:
        return self.minimum_width

    def sizeHint(self):
        """Just enough for a button: its text, plus a little."""
        text = getattr(self, "_text", "") or ""
        return types.SimpleNamespace(width=lambda: max(40, 9 * len(text) + 16),
                                     height=lambda: 24)

    def setWordWrap(self, *_a) -> None:
        pass

    def setFrameShape(self, *_a) -> None:
        pass

    def update(self) -> None:
        pass

    class NoFrame:
        pass


class QLabel(QWidget):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class QLineEdit(QWidget):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._placeholder = ""
        self.editingFinished = Signal()
        self.textChanged = Signal()

    def setText(self, text: str) -> None:
        text = str(text)
        if text == self._text:
            return
        self._text = text
        if not self._blocked:
            self.textChanged.emit(text)

    def text(self) -> str:
        return self._text

    def setPlaceholderText(self, text: str) -> None:
        self._placeholder = text

    def setReadOnly(self, on: bool) -> None:
        # Real Qt has this, and a stub without it hid a whole feature: a layer's
        # name is read-only when the layer has a role.
        self._read_only = bool(on)

    def isReadOnly(self) -> bool:
        return bool(getattr(self, "_read_only", False))

    def hasFocus(self) -> bool:
        return False


class QComboBox(QWidget):
    AdjustToMinimumContentsLengthWithIcon = 0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, object]] = []
        self._index = -1
        self.currentIndexChanged = Signal()
        self.activated = Signal()
        self._editable = False

    def addItem(self, text, data=None) -> None:
        self._items.append((str(text), data))
        if self._index < 0:
            self._index = 0

    def addItems(self, texts) -> None:
        for text in texts:
            self.addItem(text)

    def clear(self) -> None:
        self._items.clear()
        self._index = -1

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:
        return self._items[index][0]

    def currentText(self) -> str:
        if 0 <= self._index < len(self._items):
            return self._items[self._index][0]
        return ""

    def currentData(self):
        if 0 <= self._index < len(self._items):
            return self._items[self._index][1]
        return None

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self._items) or index == -1:
            self._index = index

    def findText(self, text: str) -> int:
        for i, (item, _d) in enumerate(self._items):
            if item == text:
                return i
        return -1

    def findData(self, data) -> int:
        for i, (_t, item) in enumerate(self._items):
            if item == data:
                return i
        return -1

    def setEditable(self, on: bool) -> None:
        self._editable = bool(on)

    def setCurrentText(self, text: str) -> None:
        index = self.findText(text)
        if index >= 0:
            self._index = index
        else:
            self.addItem(text)
            self._index = len(self._items) - 1

    def setMaxVisibleItems(self, *_a) -> None:
        pass

    def setSizeAdjustPolicy(self, *_a) -> None:
        pass

    def setMinimumContentsLength(self, *_a) -> None:
        pass


class QCheckBox(QWidget):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._checked = False
        self.toggled = Signal()

    def setChecked(self, on: bool) -> None:
        self._checked = bool(on)

    def isChecked(self) -> bool:
        return self._checked

    def click(self) -> None:
        self._checked = not self._checked
        self.toggled.emit(self._checked)


class QDoubleSpinBox(QWidget):
    """A number field. ``setValue`` emits, as Qt's does — the panel relies on
    that to be told about a change it did not make, so the stub must too."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._low, self._high = 0.0, 100.0
        self._decimals = 2
        self._step = 1.0
        self.valueChanged = Signal()
        self.editingFinished = Signal()

    def setRange(self, low: float, high: float) -> None:
        self._low, self._high = low, high

    def setDecimals(self, count: int) -> None:
        self._decimals = count

    def setSingleStep(self, step: float) -> None:
        self._step = step

    def value(self) -> float:
        return self._value

    def setValue(self, value: float) -> None:
        value = min(max(float(value), self._low), self._high)
        if abs(value - self._value) > 1e-12:
            self._value = value
            if not self._blocked:
                self.valueChanged.emit(value)

    def type_in(self, value: float) -> None:
        """What a user typing into it does: set, and finish."""
        self.setValue(value)
        self.editingFinished.emit()


class QSpinBox(QDoubleSpinBox):
    pass


class QPushButton(QWidget):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self.clicked = Signal()

    def text(self) -> str:
        return self._text

    def click(self) -> None:
        self.clicked.emit(False)


class QDialogButtonBox(QWidget):
    class StandardButton:
        Ok = 1
        Cancel = 2

    Ok = 1
    Cancel = 2

    def __init__(self, buttons=0, parent=None) -> None:
        super().__init__(parent)
        self.accepted = Signal()
        self.rejected = Signal()


class QDialog(QWidget):
    Accepted = 1
    Rejected = 0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._title = ""
        self._result = QDialog.Rejected

    def setWindowTitle(self, title: str) -> None:
        self._title = title

    def exec(self) -> int:
        return self._result

    def accept(self) -> None:
        self._result = QDialog.Accepted

    def reject(self) -> None:
        self._result = QDialog.Rejected


class QInputDialog(QDialog):
    _next: tuple = ("", True)

    def __init__(self, parent=None, title="", label="") -> None:
        super().__init__(parent)

    @staticmethod
    def getText(_parent, _title, _label):
        return QInputDialog._next


class QScrollArea(QWidget):
    NoFrame = 0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._widget = None

    def setWidgetResizable(self, *_a) -> None:
        pass

    def setWidget(self, widget) -> None:
        self._widget = widget

    def widget(self):
        return self._widget


class QLayout:
    def __init__(self, parent=None) -> None:
        self._items: list = []
        self._parent = parent
        if isinstance(parent, QWidget):
            parent.setLayout(self)

    def addWidget(self, widget, *stretch) -> None:
        self._items.append(widget)

    def addLayout(self, layout) -> None:
        self._items.append(layout)

    def addRow(self, *args) -> None:
        self._items.append(args)

    def addStretch(self, *_a) -> None:
        pass

    def setContentsMargins(self, *_a) -> None:
        pass

    def setSpacing(self, *_a) -> None:
        pass

    def setLabelAlignment(self, *_a) -> None:
        pass

    def setFieldGrowthPolicy(self, *_a) -> None:
        pass

    def setRowWrapPolicy(self, *_a) -> None:
        pass

    def count(self) -> int:
        return len(self._items)

    def takeAt(self, index: int):
        """Like Qt: a layout item whose ``widget()`` hands back the widget, or
        None for a nested layout."""
        item = self._items.pop(index)

        class _Item:
            def __init__(self, value):
                self._value = value

            def widget(self):
                return self._value if isinstance(self._value, QWidget) else None

            def layout(self):
                return self._value if isinstance(self._value, QLayout) else None

        return _Item(item)

    def widgets(self) -> list:
        """Every widget added, layout nesting included — what a test needs to
        find the editor for a given field."""
        out: list = []
        for item in self._items:
            if isinstance(item, QWidget):
                out.append(item)
            elif isinstance(item, QLayout):
                out.extend(item.widgets())
            elif isinstance(item, tuple):
                for part in item:
                    if isinstance(part, QWidget):
                        out.append(part)
                    elif isinstance(part, QLayout):
                        out.extend(part.widgets())
        return out


class QVBoxLayout(QLayout):
    AllNonFixedFieldsGrow = 0


class QHBoxLayout(QLayout):
    pass


class QFormLayout(QLayout):
    AllNonFixedFieldsGrow = 0
    WrapLongRows = 0


class QTimer:
    """Both shapes the extension uses: an instance whose ``timeout`` fires
    (``start``), and the static ``singleShot``."""

    def __init__(self, parent=None) -> None:
        self._parent = parent
        self._single = False
        self._msec = 0
        self._running = False
        self.timeout = Signal()

    def setSingleShot(self, on: bool) -> None:
        self._single = bool(on)

    def start(self, msec: int) -> None:
        self._msec = int(msec)
        self._running = True

    def stop(self) -> None:
        self._running = False

    def isActive(self) -> bool:
        return self._running

    def fire(self) -> None:
        """What the event loop would do when the interval is up."""
        if self._running:
            self._running = False
            self.timeout.emit()

    @staticmethod
    def singleShot(_msec, fn) -> None:
        fn()                     # run it now: no event loop in a test


class QSettings:
    """Session-only: the fold state of a panel does not belong in a test."""

    _values: dict = {}

    def value(self, key, default=None):
        return QSettings._values.get(key, default)

    def setValue(self, key, value) -> None:
        QSettings._values[key] = value


class QFileDialog:
    """Cancelled, always.

    A test that opened a real dialog would hang the run, and the import and
    export themselves are covered headlessly in ``test_openings_library.py``.
    What matters here is that a menu entry *reaches* the dialog without
    raising — the check that caught a ``NameError`` in this very extension.
    """

    #: Set this to a path and the dialog "chooses" it. Left alone, every dialog
    #: is cancelled, which is what a run of the menu entries wants.
    next_path = None

    @staticmethod
    def _answer():
        return (QFileDialog.next_path or "", "")

    @staticmethod
    def getSaveFileName(*_args, **_kwargs):
        return QFileDialog._answer()

    @staticmethod
    def getOpenFileName(*_args, **_kwargs):
        return QFileDialog._answer()


class QMessageBox(QWidget):
    """A box that is never shown: it records what it would have said."""

    INFORMATION = "information"
    WARNING = "warning"
    last: "QMessageBox | None" = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._title = ""
        self._text = ""
        QMessageBox.last = self

    def setIcon(self, _icon) -> None:
        pass

    def setWindowTitle(self, title: str) -> None:
        self._title = title

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def exec(self) -> int:
        return 0


def install() -> None:
    """Register the stub modules. Call before importing anything that uses Qt."""
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QTimer = QTimer
    qtcore.QSettings = QSettings
    qtcore.Signal = Signal
    qtcore.Qt = types.SimpleNamespace(
        DownArrow=1, RightArrow=2, ToolButtonTextBesideIcon=3,
        AlignRight=4)

    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    for name, value in (("QWidget", QWidget), ("QLabel", QLabel),
                        ("QLineEdit", QLineEdit), ("QComboBox", QComboBox),
                        ("QCheckBox", QCheckBox), ("QPushButton", QPushButton),
                        ("QDialog", QDialog), ("QInputDialog", QInputDialog),
                        ("QDialogButtonBox", QDialogButtonBox),
                        ("QScrollArea", QScrollArea),
                        ("QFileDialog", QFileDialog),
                        ("QMessageBox", QMessageBox),
                        ("QDoubleSpinBox", QDoubleSpinBox),
                        ("QSpinBox", QSpinBox),
                        ("QVBoxLayout", QVBoxLayout),
                        ("QHBoxLayout", QHBoxLayout),
                        ("QFormLayout", QFormLayout),
                        ("QToolButton", QPushButton),
                        ("QFrame", QWidget)):
        setattr(qtwidgets, name, value)

    pyside = types.ModuleType("PySide6")
    pyside.__path__ = []
    pyside.QtCore = qtcore
    pyside.QtWidgets = qtwidgets

    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtWidgets"] = qtwidgets

    # views.fold_section: the real one is Qt-heavy, and its behaviour (a body
    # the caller fills, a remembered open state) is all the panel relies on.
    fold = types.ModuleType("views.fold_section")

    class FoldSection(QWidget):
        def __init__(self, title: str, settings_key: str, parent=None,
                     default_open: bool = True) -> None:
            super().__init__(parent)
            self.title = title
            self.settings_key = settings_key
            # Like the real one: an empty body, with no layout of its own — the
            # caller installs what it wants.
            self.body = QWidget(self)
            self.open = default_open

        def set_open(self, on: bool) -> None:
            self.open = bool(on)

    def narrow(*widgets) -> None:
        """Faithful, unlike my first version: ``views.fold_section.narrow``
        sets the horizontal size policy to ``Ignored`` and a 40 px minimum, so
        a control in a row *with* a stretch can be squeezed to a sliver. That is
        what a combo box or a spin box should do and what a button must not —
        and it is invisible unless this stub models it."""
        for w in widgets:
            if isinstance(w, QComboBox):
                w.setMinimumContentsLength(6)
            else:
                w.size_policy_ignored = True
                w.setMinimumWidth(40)

    def wrapping_form(parent) -> QFormLayout:
        return QFormLayout(parent)

    fold.FoldSection = FoldSection
    fold.narrow = narrow
    fold.wrapping_form = wrapping_form
    views = types.ModuleType("views")
    views.__path__ = []
    views.fold_section = fold
    dialogs = types.ModuleType("views.filedialogs")

    class _FileDialogs:
        #: Set to a path and the dialog "chooses" it; left alone, it cancels.
        next_path = None

        @staticmethod
        def getSaveFileName(*_a, **_k):
            return (_FileDialogs.next_path or "", "")

        @staticmethod
        def getOpenFileName(*_a, **_k):
            return (_FileDialogs.next_path or "", "")

    dialogs.file_dialogs = _FileDialogs
    shortcuts = types.ModuleType("views.shortcuts")
    shortcuts.set_tooltip = lambda action, tip: action.setToolTip(tip)
    views.shortcuts = shortcuts
    sys.modules["views"] = views
    sys.modules["views.fold_section"] = fold
    sys.modules["views.shortcuts"] = shortcuts
    views.filedialogs = dialogs
    sys.modules["views.filedialogs"] = dialogs
