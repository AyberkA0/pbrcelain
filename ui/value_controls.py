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

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
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
        if event.type() == QEvent.Type.ShortcutOverride and _is_history_key(event):
            parent = obj.parentWidget() if isinstance(obj, QWidget) else None
            if isinstance(obj, QAbstractSpinBox) or isinstance(parent, QAbstractSpinBox):
                event.ignore()
                return True
            return False
        if event.type() != QEvent.Type.Wheel:
            return False
        target = obj
        while target is not None and not isinstance(target, (QAbstractSpinBox, QComboBox, QSlider, Knob)):
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


def _is_history_key(event) -> bool:
    from PyQt6.QtGui import QKeySequence

    if event.matches(QKeySequence.StandardKey.Undo) or event.matches(QKeySequence.StandardKey.Redo):
        return True
    return event.key() == Qt.Key.Key_Y and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)


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


def _own_enabled(spin) -> bool:
    """Whether the spin box itself was disabled, ignoring a disabled parent.
    Copying isEnabled() would force-disable the control when its section is
    switched off, and it would then stay disabled when the section comes back."""
    return not spin.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled)


def wants_slider(spin: QAbstractSpinBox) -> bool:
    # Every bounded number gets the same control (knob in sections, slider
    # inline) so equal kinds of value never look different.
    if isinstance(spin, (QDoubleSpinBox, QSpinBox)):
        return spin.maximum() - spin.minimum() > 0
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
        self.setEnabled(_own_enabled(spin))

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
            self.setEnabled(_own_enabled(self._spin))
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


class Knob(QWidget):
    """A rotary control in the style of a mixer knob, bound to a spin box.

    Drag up/right to turn it clockwise, down/left to turn it back (Option: fine,
    Shift: coarse). The mouse wheel works once the knob has focus, and a
    double-click restores `default`. The spin box stays the single source of
    truth; it is kept inside the knob, hidden.
    """

    _SWEEP = 270.0

    def __init__(self, spin: QAbstractSpinBox, default: float, diameter: int = 46, parent=None):
        super().__init__(parent)
        self._spin = spin
        self._default = default
        self._drag_origin = None
        self._drag_value = 0.0
        spin.setParent(self)
        spin.hide()
        spin.valueChanged.connect(self.update)
        spin.installEventFilter(self)
        self._diameter = diameter
        self.setFixedSize(diameter + 6, diameter + 18)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        tip = spin.toolTip()
        hint = "Drag up/down to turn (Option: fine, Shift: coarse). Double-click to reset."
        self.setToolTip(f"{tip}\n\n{hint}" if tip else hint)
        self.setEnabled(_own_enabled(spin))

    def _set(self, value: float) -> None:
        # QSpinBox only accepts ints; a float raises and would abort the app.
        if _is_int(self._spin):
            self._spin.setValue(int(round(value)))
        else:
            self._spin.setValue(float(value))

    def _fraction(self) -> float:
        lo, hi = self._spin.minimum(), self._spin.maximum()
        return 0.0 if hi <= lo else (float(self._spin.value()) - lo) / (hi - lo)

    def _per_pixel(self, modifiers) -> float:
        per_px = (self._spin.maximum() - self._spin.minimum()) / 200.0
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            per_px *= 4.0
        if modifiers & Qt.KeyboardModifier.AltModifier:
            per_px *= 0.1
        return per_px

    def eventFilter(self, obj, event) -> bool:
        if obj is self._spin and event.type() == QEvent.Type.EnabledChange:
            self.setEnabled(_own_enabled(self._spin))
            self.update()
        return False

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position()
            self._drag_value = float(self._spin.value())
            self.setFocus(Qt.FocusReason.MouseFocusReason)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is None:
            return
        delta = event.position() - self._drag_origin
        travel = (-delta.y()) + delta.x()
        self._set(self._drag_value + travel * self._per_pixel(event.modifiers()))

    def mouseReleaseEvent(self, event) -> None:
        self._drag_origin = None

    def mouseDoubleClickEvent(self, event) -> None:
        self._set(self._default)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        self._set(float(self._spin.value()) + steps * self._spin.singleStep())

    def paintEvent(self, event) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QPainter, QPalette, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        enabled = self.isEnabled()
        text = pal.color(QPalette.ColorRole.WindowText)
        accent = pal.color(QPalette.ColorRole.Highlight) if enabled else text
        track = QColor(text)
        track.setAlphaF(0.16)
        if not enabled:
            accent = QColor(text)
            accent.setAlphaF(0.35)

        side = self._diameter
        rect = QRectF(3, 3, side, side)
        start = 225.0
        span = -self._SWEEP

        pen = QPen(track, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, int(start * 16), int(span * 16))
        pen.setColor(accent)
        painter.setPen(pen)
        painter.drawArc(rect, int(start * 16), int(span * self._fraction() * 16))

        body = rect.adjusted(8, 8, -8, -8)
        fill = QColor(text)
        fill.setAlphaF(0.10 if enabled else 0.05)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(body)

        import math

        angle = math.radians(start + span * self._fraction())
        cx, cy = body.center().x(), body.center().y()
        r_out = body.width() / 2 - 3
        r_in = r_out * 0.45
        mark = QColor(text)
        if not enabled:
            mark.setAlphaF(0.4)
        painter.setPen(QPen(mark, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(
            QPointF(cx + r_in * math.cos(angle), cy - r_in * math.sin(angle)),
            QPointF(cx + r_out * math.cos(angle), cy - r_out * math.sin(angle)),
        )

        painter.setPen(mark)
        font = painter.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() - 2))
        painter.setFont(font)
        value_text = self._spin.textFromValue(self._spin.value()) + self._spin.suffix()
        bottom = QRectF(rect.center().x() - self.width() / 2, rect.bottom() - 2, self.width(), 16)
        painter.drawText(bottom, Qt.AlignmentFlag.AlignCenter, value_text)
        painter.end()
