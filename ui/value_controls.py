"""Comfort helpers for numeric property widgets.

- A wheel guard so scrolling a panel never changes a value the pointer happens
  to pass over: spin boxes, combo boxes and sliders only take the wheel once
  they have focus.
- Drag-to-scrub on a parameter's label (Unity style): drag left/right to change
  the value, Option/Alt for fine steps, Shift for coarse steps.
- A slider paired with a spin box for values whose range is narrow enough to
  drag across comfortably.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_SLIDER_STEPS = 1000
_FIELD_WIDTH = 100


class _WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Polish and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            if obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            return False
        if event.type() != QEvent.Type.Wheel:
            return False
        target = obj
        while target is not None and not isinstance(target, (QAbstractSpinBox, QComboBox, QSlider)):
            if isinstance(target, QAbstractScrollArea):
                return False
            target = target.parentWidget() if isinstance(target, QWidget) else None
        if target is None or target.hasFocus():
            return False
        parent = target.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            QApplication.sendEvent(parent.viewport(), event.clone())
        return True


_guard: _WheelGuard | None = None


def install_wheel_guard(app: QApplication) -> None:
    global _guard
    if _guard is None:
        _guard = _WheelGuard(app)
        app.installEventFilter(_guard)


def _is_int(spin: QAbstractSpinBox) -> bool:
    return isinstance(spin, QSpinBox)


class _Scrubber(QObject):
    def __init__(self, label: QLabel, spin: QAbstractSpinBox):
        super().__init__(label)
        self._label = label
        self._spin = spin
        self._origin_x: float | None = None
        self._origin_value = 0.0
        self._moved = False
        label.setCursor(Qt.CursorShape.SizeHorCursor)
        tip = label.toolTip()
        hint = "Drag left/right to adjust (Option: fine, Shift: coarse)"
        label.setToolTip(f"{tip}\n\n{hint}" if tip else hint)
        label.installEventFilter(self)

    def _step_per_pixel(self, modifiers) -> float:
        spin = self._spin
        span = spin.maximum() - spin.minimum()
        step = spin.singleStep()
        if _is_int(spin):
            per_px = max(step, span / 300.0) / 4.0
        else:
            per_px = max(step / 4.0, span / 600.0)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            per_px *= 10.0
        if modifiers & Qt.KeyboardModifier.AltModifier:
            per_px *= 0.1
        return per_px

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if not self._spin.isEnabled():
            return False
        if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._origin_x = event.position().x()
            self._origin_value = float(self._spin.value())
            self._moved = False
            return True
        if etype == QEvent.Type.MouseMove and self._origin_x is not None:
            dx = event.position().x() - self._origin_x
            if not self._moved and abs(dx) < 2:
                return True
            self._moved = True
            value = self._origin_value + dx * self._step_per_pixel(event.modifiers())
            self._spin.setValue(int(round(value)) if _is_int(self._spin) else value)
            return True
        if etype == QEvent.Type.MouseButtonRelease and self._origin_x is not None:
            self._origin_x = None
            if not self._moved:
                self._spin.setFocus(Qt.FocusReason.MouseFocusReason)
                self._spin.selectAll()
            return True
        return False


def attach_scrub(label: QLabel, spin: QAbstractSpinBox) -> None:
    _Scrubber(label, spin)


def wants_slider(spin: QAbstractSpinBox) -> bool:
    span = spin.maximum() - spin.minimum()
    if isinstance(spin, QDoubleSpinBox):
        return 0 < span <= 10.0
    if isinstance(spin, QSpinBox):
        return 0 < span <= 100
    return False


class _SpinSlider(QSlider):
    def __init__(self, spin: QAbstractSpinBox):
        super().__init__(Qt.Orientation.Horizontal)
        self._spin = spin
        self._int = _is_int(spin)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumWidth(40)
        if self._int:
            self.setRange(int(spin.minimum()), int(spin.maximum()))
        else:
            self.setRange(0, _SLIDER_STEPS)
        if spin.toolTip():
            self.setToolTip(spin.toolTip())
        self._sync()
        spin.valueChanged.connect(self._sync)
        self.valueChanged.connect(self._push)
        spin.installEventFilter(self)
        self.setEnabled(spin.isEnabled())

    def _to_slider(self, value: float) -> int:
        if self._int:
            return int(value)
        lo, hi = self._spin.minimum(), self._spin.maximum()
        return int(round((value - lo) / (hi - lo) * _SLIDER_STEPS))

    def _sync(self, *_args) -> None:
        self.blockSignals(True)
        self.setValue(self._to_slider(float(self._spin.value())))
        self.blockSignals(False)

    def _push(self, pos: int) -> None:
        if self._int:
            self._spin.setValue(pos)
            return
        lo, hi = self._spin.minimum(), self._spin.maximum()
        self._spin.setValue(lo + (hi - lo) * pos / _SLIDER_STEPS)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._spin and event.type() == QEvent.Type.EnabledChange:
            self.setEnabled(self._spin.isEnabled())
        return False


def slider_field(spin: QAbstractSpinBox, stacked: bool) -> QWidget:
    """Wrap `spin` with a slider. `stacked` puts the slider under the field
    (for narrow grid cells); otherwise they sit side by side."""
    host = QWidget()
    slider = _SpinSlider(spin)
    if stacked:
        layout = QVBoxLayout(host)
        layout.setSpacing(2)
        layout.addWidget(spin)
        layout.addWidget(slider)
    else:
        layout = QHBoxLayout(host)
        layout.setSpacing(10)
        spin.setFixedWidth(_FIELD_WIDTH)
        layout.addWidget(slider, 1)
        layout.addWidget(spin)
    layout.setContentsMargins(0, 0, 0, 0)
    return host


def find_spin(widget: QWidget) -> QAbstractSpinBox | None:
    if isinstance(widget, QAbstractSpinBox):
        return widget
    spins = widget.findChildren(QAbstractSpinBox)
    return spins[0] if len(spins) == 1 else None
