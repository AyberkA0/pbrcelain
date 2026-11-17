from __future__ import annotations

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
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
    def __init__(self, grid: QGridLayout):
        self.grid = grid
        self.row = 0
        self.col = 0


def _configure_grid(grid: QGridLayout) -> None:
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(12)
    for c in range(COLUMNS):
        grid.setColumnStretch(c, 1)


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

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def add_param(self, label_text: str, widget: QWidget, wide: bool = False, share_cell: bool = False) -> QWidget:
        """`share_cell` places the parameter in the same grid cell as the previous
        one, for alternatives of which only one is shown at a time."""
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
            elif spin is widget and wants_slider(spin):
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
        if wide or inline:
            self.add_wide(container)
            return container
        cur = self._cursor
        if share_cell and (cur.row, cur.col) != (0, 0):
            row, col = (cur.row, cur.col - 1) if cur.col > 0 else (cur.row - 1, COLUMNS - 1)
            cur.grid.addWidget(container, row, col, Qt.AlignmentFlag.AlignTop)
            return container
        cur.grid.addWidget(container, cur.row, cur.col, Qt.AlignmentFlag.AlignTop)
        cur.col += 1
        if cur.col >= COLUMNS:
            cur.col = 0
            cur.row += 1
        return container

    def add_section(self, title: str, toggle: QCheckBox | None = None) -> None:
        """Start a foldout group. Parameters added until end_section() or the next
        add_section() live inside it. `toggle` puts that checkbox in the header so
        the feature can be switched without opening the group."""
        self.end_section()
        key = f"sections/{self._settings_key}/{title}"
        expanded = QSettings().value(key, True, type=bool) is not False
        header = SectionHeader(title, expanded, toggle)
        header.setToolTip("Click to show or hide these settings")
        self.add_wide(header)

        body = QWidget()
        grid = QGridLayout(body)
        _configure_grid(grid)
        grid.setContentsMargins(18, 0, 0, 2)
        body.setVisible(expanded)
        self.add_wide(body)
        self._cursor = _GridCursor(grid)
        self.sections[title] = (header, body)

        def on_toggled(state: bool, body=body, key=key) -> None:
            body.setVisible(state)
            QSettings().setValue(key, state)

        header.toggled.connect(on_toggled)
        if toggle is not None:
            body.setEnabled(toggle.isChecked())
            toggle.toggled.connect(body.setEnabled)

    def end_section(self) -> None:
        self._cursor = self._root

    def add_wide(self, widget: QWidget) -> None:
        cur = self._cursor
        if cur.col != 0:
            cur.row += 1
            cur.col = 0
        cur.grid.addWidget(widget, cur.row, 0, 1, COLUMNS)
        cur.row += 1

    def add_stretch(self) -> None:
        self.end_section()
        self._root.grid.setRowStretch(self._root.row + 1, 1)


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

        self.stack = QStackedWidget()
        self.stack.addWidget(self.generate_page)
        self.stack.addWidget(self.properties_page)
        layout.addWidget(self.stack, 1)

    def select_page(self, name: str) -> None:
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
