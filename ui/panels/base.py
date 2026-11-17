from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import IS_MAC, PLATFORM_THEME, pick
from ui.value_controls import Knob, attach_scrub, find_spin, slider_field, wants_slider
from ui.widgets import FoldArrow

COLUMNS = 3
_SCROLLBAR_ROOM = 16


class SectionHeader(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, expanded: bool = True, checkbox: QCheckBox | None = None, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._arrow = FoldArrow(expanded)
        row.addWidget(self._arrow)
        if checkbox is not None:
            label = checkbox.text()
            if not checkbox.toolTip():
                checkbox.setToolTip(label)
            checkbox.setAccessibleName(label)
            checkbox.setText("")
            checkbox.setCursor(Qt.CursorShape.ArrowCursor)
            row.addWidget(checkbox)
        title_label = QLabel(title)
        title_label.setProperty("role", "panel-title")
        row.addWidget(title_label)
        row.addStretch(1)
        self._refresh()

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._refresh()
        self.toggled.emit(expanded)

    def _refresh(self) -> None:
        self._arrow.set_expanded(self._expanded)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.set_expanded(not self._expanded)
        super().mouseReleaseEvent(event)


class _GridCursor:
    """Where the next parameter goes, plus the order everything was added in,
    so the grid can be laid out again when the panel width changes."""

    def __init__(self, grid: QGridLayout, indent: int = 0):
        self.grid = grid
        self.row = 0
        self.col = 0
        self.indent = indent
        # ("cell", [widgets]) | ("wide", widget) | ("break",) | ("stretch",)
        self.entries: list[tuple] = []
        self.own_row: frozenset[int] = frozenset()


def _combo_too_narrow(widgets: list[QWidget], cell_width: float) -> bool:
    """True when a combo box in the cell cannot show its longest item."""
    for widget in widgets:
        combos = widget.findChildren(QComboBox)
        if isinstance(widget, QComboBox):
            combos.append(widget)
        for combo in combos:
            fm = combo.fontMetrics()
            longest = max((fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
            if longest + 44 > cell_width:
                return True
    return False


def _configure_grid(grid: QGridLayout) -> None:
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(12)
    for c in range(COLUMNS):
        grid.setColumnStretch(c, 1)


def _lay_out(cur: _GridCursor) -> None:
    """Place the recorded entries again, honouring `cur.own_row`."""
    grid = cur.grid
    for entry in cur.entries:
        if entry[0] == "cell":
            for widget in entry[1]:
                grid.removeWidget(widget)
        elif entry[0] == "wide":
            grid.removeWidget(entry[1])
    for r in range(grid.rowCount()):
        grid.setRowStretch(r, 0)

    row = 0
    pending: list[int] = []

    def flush() -> None:
        nonlocal row
        alone = [i for i in pending if i in cur.own_row]
        rest = [i for i in pending if i not in cur.own_row]
        for i in alone:
            for widget in cur.entries[i][1]:
                grid.addWidget(widget, row, 0, 1, COLUMNS, Qt.AlignmentFlag.AlignTop)
            row += 1
        for col, i in enumerate(rest):
            for widget in cur.entries[i][1]:
                grid.addWidget(widget, row, col, Qt.AlignmentFlag.AlignTop)
        if rest:
            row += 1
        pending.clear()

    for i, entry in enumerate(cur.entries):
        kind = entry[0]
        if kind == "cell":
            pending.append(i)
            if len(pending) == COLUMNS:
                flush()
        else:
            flush()
            if kind == "wide":
                grid.addWidget(entry[1], row, 0, 1, COLUMNS)
                row += 1
            elif kind == "stretch":
                grid.setRowStretch(row + 1, 1)
    flush()
    cur.row, cur.col = row, 0


class PropertyPanel(QWidget):
    def __init__(self, settings_key: str = "", parent=None):
        super().__init__(parent)
        self._settings_key = settings_key
        self.sections: dict[str, tuple[SectionHeader, QWidget]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        grid = QGridLayout(content)
        _configure_grid(grid)
        grid.setContentsMargins(*pick(mac=(14, 12, 14, 14), windows=(16, 12, 16, 16), legacy=(10, 10, 10, 10)))
        self._root = _GridCursor(grid)
        self._cursor = self._root
        self._cursors = [self._root]
        self._content = content

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def add_param(
        self,
        label_text: str,
        widget: QWidget,
        wide: bool = False,
        share_cell: bool = False,
        plain: bool = False,
        _place: bool = True,
    ) -> QWidget:
        """`share_cell` places the parameter in the same grid cell as the previous
        one, for alternatives of which only one is shown at a time. `plain` keeps a
        number as a spin box instead of a knob or slider, for counts like a batch size."""
        inline = self._cursor is self._root
        container = QWidget()
        if inline:
            v = QHBoxLayout(container)
            v.setSpacing(10)
        else:
            v = QVBoxLayout(container)
            v.setSpacing(3)
        v.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setProperty("role", "dim")
        if not inline:
            label.setWordWrap(True)
        v.addWidget(label)
        spin = find_spin(widget)
        tip = widget.toolTip() or (spin.toolTip() if spin is not None else "")
        if tip:
            label.setToolTip(tip)
        field = widget
        if spin is not None:
            attach_scrub(label, spin)
            if isinstance(widget, Knob):
                pass
            elif spin is widget and not plain and wants_slider(spin):
                field = slider_field(spin, stacked=False) if inline else Knob(spin, default=float(spin.value()))
        if isinstance(field, Knob):
            v.addWidget(field, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            v.addWidget(field, 1 if inline else 0)
        for spin_box in ([widget] if isinstance(widget, QAbstractSpinBox) else widget.findChildren(QAbstractSpinBox)):
            if spin_box.isVisibleTo(widget) or spin_box is widget:
                spin_box.setMinimumWidth(56)
        if PLATFORM_THEME != "legacy":
            combos = widget.findChildren(QComboBox)
            if isinstance(widget, QComboBox):
                combos.append(widget)
            for combo in combos:
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(4)
                combo.setMinimumWidth(64)
        if not _place:
            return container
        if wide or inline:
            self.add_wide(container)
            return container
        cur = self._cursor
        if share_cell and (cur.row, cur.col) != (0, 0):
            row, col = (cur.row, cur.col - 1) if cur.col > 0 else (cur.row - 1, COLUMNS - 1)
            cur.grid.addWidget(container, row, col, Qt.AlignmentFlag.AlignTop)
            for entry in reversed(cur.entries):
                if entry[0] == "cell":
                    entry[1].append(container)
                    break
            return container
        cur.entries.append(("cell", [container]))
        cur.grid.addWidget(container, cur.row, cur.col, Qt.AlignmentFlag.AlignTop)
        cur.col += 1
        if cur.col >= COLUMNS:
            cur.col = 0
            cur.row += 1
        return container

    def add_pair(self, first: tuple[str, QWidget], second: tuple[str, QWidget]) -> None:
        """Two parameters sharing one full-width row, half the width each."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self._root.grid.horizontalSpacing())
        for label_text, widget in (first, second):
            layout.addWidget(self.add_param(label_text, widget, _place=False), 1, Qt.AlignmentFlag.AlignTop)
        self.add_wide(row)

    def add_section(self, title: str, toggle: QCheckBox | None = None, expanded: bool = False) -> None:
        """Start a foldout group. Parameters added until end_section() or the next
        add_section() live inside it. `toggle` puts that checkbox in the header so
        the feature can be switched without opening the group. Groups start
        folded so a page opens as a short overview; `expanded` opens one."""
        self.end_section()
        header = SectionHeader(title, expanded, toggle)
        header.setToolTip("Click to show or hide these settings")
        self.add_wide(header)

        body = QWidget()
        grid = QGridLayout(body)
        _configure_grid(grid)
        grid.setContentsMargins(18, 0, 0, 2)
        body.setVisible(expanded)
        self.add_wide(body)
        self._cursor = _GridCursor(grid, indent=18)
        self._cursors.append(self._cursor)
        self.sections[title] = (header, body)

        header.toggled.connect(body.setVisible)
        if toggle is not None:
            body.setEnabled(toggle.isChecked())
            toggle.toggled.connect(body.setEnabled)

    def new_row(self) -> None:
        """Start the next parameter on a fresh row, so unlike controls (swatches,
        knobs) are not mixed in one row."""
        cur = self._cursor
        cur.entries.append(("break",))
        if cur.col != 0:
            cur.row += 1
            cur.col = 0

    def end_section(self) -> None:
        self._cursor = self._root

    def add_wide(self, widget: QWidget) -> None:
        cur = self._cursor
        cur.entries.append(("wide", widget))
        if cur.col != 0:
            cur.row += 1
            cur.col = 0
        cur.grid.addWidget(widget, cur.row, 0, 1, COLUMNS)
        cur.row += 1

    def add_stretch(self) -> None:
        self.end_section()
        self._root.entries.append(("stretch",))
        self._root.grid.setRowStretch(self._root.row + 1, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """A combo box that cannot show its text in a third of the width gets a
        row of its own; the parameters that shared its row move to the next one."""
        margins = self._root.grid.contentsMargins()
        # Measured on the panel, with room for a scroll bar either way: the
        # content width changes when a scroll bar appears, and deciding on it
        # could flip the layout back and forth.
        avail = self.width() - _SCROLLBAR_ROOM - margins.left() - margins.right()
        spacing = self._root.grid.horizontalSpacing()
        for cur in self._cursors:
            cell_width = (avail - cur.indent - spacing * (COLUMNS - 1)) / COLUMNS
            own_row = frozenset(
                i for i, entry in enumerate(cur.entries)
                if entry[0] == "cell" and _combo_too_narrow(entry[1], cell_width)
            )
            if own_row != cur.own_row:
                cur.own_row = own_row
                _lay_out(cur)



class GeneratePropertiesContainer(QWidget):
    pageChanged = pyqtSignal(str)
    propertiesChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generate_page = PropertyPanel(f"{type(self).__name__}/generate")
        self.properties_page = PropertyPanel(f"{type(self).__name__}/properties")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(6, 6, 6, 0)
        if IS_MAC:
            tabs_row.setContentsMargins(14, 4, 14, 2)
            segment = QWidget()
            segment.setObjectName("SubtabBar")
            segment.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            segment_layout = QHBoxLayout(segment)
            segment_layout.setContentsMargins(2, 2, 2, 2)
            segment_layout.setSpacing(2)
        self.generate_tab_btn = QPushButton("Generate")
        self.properties_tab_btn = QPushButton("Adjustment")
        for btn in (self.generate_tab_btn, self.properties_tab_btn):
            btn.setCheckable(True)
            btn.setProperty("role", "subtab")
        self.generate_tab_btn.setChecked(True)
        self.generate_tab_btn.clicked.connect(lambda: self.select_page("generate"))
        self.properties_tab_btn.clicked.connect(lambda: self.select_page("properties"))
        if IS_MAC:
            segment_layout.addWidget(self.generate_tab_btn)
            segment_layout.addWidget(self.properties_tab_btn)
            tabs_row.addWidget(segment, 1)
        else:
            tabs_row.addWidget(self.generate_tab_btn)
            tabs_row.addWidget(self.properties_tab_btn)
            tabs_row.addStretch(1)
        layout.addLayout(tabs_row)
        self._single_page = False

        self.stack = QStackedWidget()
        self.stack.addWidget(self.generate_page)
        self.stack.addWidget(self.properties_page)
        layout.addWidget(self.stack, 1)

    def sync_knob_defaults(self) -> None:
        """Make double-clicking a knob restore the same value the panel's Reset
        buttons do: run the resets, read the values off, then put every control
        back the way it was."""
        spins = {spin: spin.value() for spin in self.findChildren(QAbstractSpinBox)}
        combos = {combo: combo.currentIndex() for combo in self.findChildren(QComboBox)}
        checks = {box: box.isChecked() for box in self.findChildren(QCheckBox)}
        for name in ("reset_generate_defaults", "reset_to_defaults"):
            reset = getattr(self, name, None)
            if reset is not None:
                reset()
        for knob in self.findChildren(Knob):
            knob.set_default(knob.spin_box().value())
        for combo, index in combos.items():
            combo.setCurrentIndex(index)
        for box, checked in checks.items():
            box.setChecked(checked)
        for spin, value in spins.items():
            spin.setValue(value)

    def set_single_page(self) -> None:
        """For maps with nothing to generate: the switch offers only Adjustment."""
        self._single_page = True
        self.generate_tab_btn.hide()
        self.select_page("properties")

    def select_page(self, name: str) -> None:
        if self._single_page:
            name = "properties"
        if name == "properties":
            self.stack.setCurrentWidget(self.properties_page)
            self.properties_tab_btn.setChecked(True)
            self.generate_tab_btn.setChecked(False)
        else:
            name = "generate"
            self.stack.setCurrentWidget(self.generate_page)
            self.generate_tab_btn.setChecked(True)
            self.properties_tab_btn.setChecked(False)
        self.pageChanged.emit(name)

    def current_page(self) -> str:
        return "properties" if self.stack.currentWidget() is self.properties_page else "generate"
