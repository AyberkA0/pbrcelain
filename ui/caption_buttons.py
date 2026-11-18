"""Windows minimize, maximize/restore and close buttons for the frameless window.

They sit in the window's top-right corner on a floating background, drawn like
the Windows 11 caption buttons: thin glyphs, a light hover tint, and a red
close button on hover.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout

BUTTON_WIDTH = 46
_GLYPH = 10.0
_CLOSE_HOVER = QColor("#c42b1c")
_CLOSE_PRESSED = QColor("#c84031")


class _CaptionButton(QAbstractButton):
    def __init__(self, kind: str, window, height: int, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._window = window
        self._native_hover = False
        self._native_pressed = False
        self.setFixedSize(BUTTON_WIDTH, height)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        name = {"minimize": "Minimize", "maximize": "Maximize", "close": "Close"}[kind]
        self.setAccessibleName(name)

    def sizeHint(self) -> QSize:
        return QSize(BUTTON_WIDTH, self.height())

    def set_native_state(self, hover: bool, pressed: bool | None = None) -> None:
        """Hover/pressed reported by Windows while the pointer is on the
        maximize button as a non-client area (Windows 11 Snap Layouts)."""
        if pressed is None:
            pressed = self._native_pressed and hover
        if (hover, pressed) != (self._native_hover, self._native_pressed):
            self._native_hover, self._native_pressed = hover, pressed
            self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.WindowText)
        hovered = self.underMouse() or self._native_hover
        pressed = self.isDown() or self._native_pressed

        glyph = QColor(text)
        if hovered or pressed:
            if self._kind == "close":
                painter.fillRect(self.rect(), _CLOSE_PRESSED if pressed else _CLOSE_HOVER)
                glyph = QColor("white")
            else:
                tint = QColor(text)
                tint.setAlphaF(0.06 if pressed else 0.10)
                painter.fillRect(self.rect(), tint)
                if pressed:
                    glyph.setAlphaF(0.7)
        elif not self._window.isActiveWindow():
            glyph.setAlphaF(0.45)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, self._kind == "close")
        pen = QPen(glyph, 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Glyph box, snapped to whole pixels so the 1 px lines stay crisp.
        x = round((self.width() - _GLYPH) / 2) + 0.5
        y = round((self.height() - _GLYPH) / 2) + 0.5
        s = _GLYPH - 1
        if self._kind == "minimize":
            mid = y + s / 2
            painter.drawLine(QPointF(x, mid), QPointF(x + s, mid))
        elif self._kind == "maximize":
            if self._window.isMaximized():
                # Restore: a front square and the corner of one behind it.
                d = 2.0
                painter.drawRect(QRectF(x, y + d, s - d, s - d))
                painter.drawLine(QPointF(x + d, y), QPointF(x + s, y))
                painter.drawLine(QPointF(x + s, y), QPointF(x + s, y + s - d))
            else:
                painter.drawRect(QRectF(x, y, s, s))
        else:
            painter.drawLine(QPointF(x, y), QPointF(x + s, y + s))
            painter.drawLine(QPointF(x + s, y), QPointF(x, y + s))
        painter.end()


class CaptionButtons(QFrame):
    def __init__(self, window, height: int, parent=None):
        super().__init__(parent)
        self.setObjectName("CaptionButtons")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        # Room for the floating background's left edge and rounded corner.
        row.setContentsMargins(1, 0, 0, 1)
        row.setSpacing(0)
        self.minimize_button = _CaptionButton("minimize", window, height, self)
        self.maximize_button = _CaptionButton("maximize", window, height, self)
        self.close_button = _CaptionButton("close", window, height, self)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            row.addWidget(button)
        self.setFixedSize(3 * BUTTON_WIDTH + 1, height + 1)
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(
            lambda: window.showNormal() if window.isMaximized() else window.showMaximized()
        )
        self.close_button.clicked.connect(window.close)

    def refresh(self) -> None:
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.update()
