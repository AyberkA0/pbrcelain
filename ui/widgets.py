from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QPainterPath, QPalette, QPixmap
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from ui.theme import PLATFORM_THEME


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


class SlotButton(QPushButton):
    doubleClicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ImageLabel(QLabel):
    imageDropped = pyqtSignal(str)
    fileDropped = pyqtSignal(str)
    doubleClicked = pyqtSignal()

    def __init__(self, placeholder_text: str = "No image", parent=None):
        super().__init__(parent)
        self._source_pixmap: QPixmap | None = None
        self._placeholder_text = placeholder_text
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 200)
        if PLATFORM_THEME == "legacy":
            self.setStyleSheet("background-color: #1a1a1a; color: #8a8a8a; border: 1px solid #202020; border-radius: 2px;")
        self.setText(placeholder_text)
        self.setAcceptDrops(True)

    def set_pixmap_source(self, pixmap: QPixmap | None) -> None:
        self._source_pixmap = pixmap
        if pixmap is None:
            self.setText(self._placeholder_text)
            self.setToolTip("")
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self._rescale()
            self.setToolTip("Double-click to open 2x2 Tiled Seamless Preview")
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def clear_image(self) -> None:
        self.set_pixmap_source(None)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def _rescale(self) -> None:
        if self._source_pixmap is None:
            return
        dpr = self.devicePixelRatioF()
        scaled = self._source_pixmap.scaled(
            self.size() * dpr,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        super().setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            self._rescale()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            super().dropEvent(event)
            return
        path = urls[0].toLocalFile()
        event.acceptProposedAction()
        if path.lower().endswith(IMAGE_EXTENSIONS):
            self.imageDropped.emit(path)
        else:
            self.fileDropped.emit(path)


class ToggleHeading(QLabel):
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self.setText(self._title)
        self.setIndent(_ARROW_BOX + 7)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        rect = self.contentsRect()
        paint_fold_arrow(painter, rect.left(), rect.top(), _ARROW_BOX, rect.height(), self._expanded, color)
        painter.end()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.set_expanded(not self._expanded)
        super().mouseReleaseEvent(event)


_ARROW_BOX = 14


def paint_fold_arrow(painter: QPainter, x: float, y: float, w: float, h: float, expanded: bool, color) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy = x + w / 2, y + h / 2
    r = 4.5
    path = QPainterPath()
    if expanded:
        path.moveTo(cx - r, cy - r * 0.55)
        path.lineTo(cx + r, cy - r * 0.55)
        path.lineTo(cx, cy + r * 0.75)
    else:
        path.moveTo(cx - r * 0.55, cy - r)
        path.lineTo(cx - r * 0.55, cy + r)
        path.lineTo(cx + r * 0.75, cy)
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


class FoldArrow(QWidget):
    def __init__(self, expanded: bool = True, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self.setFixedSize(_ARROW_BOX + 2, _ARROW_BOX + 2)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        paint_fold_arrow(painter, 0, 0, self.width(), self.height(), self._expanded, color)
        painter.end()


class _Halo(QWidget):
    """Paints a soft rounded glow; sits behind the widget it highlights."""

    SPREAD = 16

    def __init__(self, parent):
        super().__init__(parent)
        from PyQt6.QtGui import QColor

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.color = QColor("#0a84ff")
        self.strength = 0.0
        self.radius = 9.0

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import QColor

        if self.strength <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        steps = self.SPREAD
        inner = QRectF(self.rect()).adjusted(steps, steps, -steps, -steps)
        hole = QPainterPath()
        hole.addRoundedRect(inner, self.radius, self.radius)
        painter.setClipPath(self._outside(hole))
        for i in range(steps, 0, -1):
            k = 1.0 - i / (steps + 1)
            color = QColor(self.color)
            color.setAlphaF(min(1.0, self.strength * 0.16 * k * k))
            painter.setBrush(color)
            painter.drawRoundedRect(inner.adjusted(-i, -i, i, i), self.radius + i, self.radius + i)
        painter.end()

    def _outside(self, hole):
        whole = QPainterPath()
        whole.addRect(QRectF(self.rect()))
        return whole.subtracted(hole)


class PulseGlow:
    """A soft glow that slowly breathes around a widget, used to point at the
    next step (e.g. the Albedo slot of an empty project). The glow is painted
    on `host` behind the widget so neighbouring layout margins do not clip it."""

    def __init__(self, widget, color, host=None, period_ms: int = 1200):
        from PyQt6.QtCore import QEasingCurve, QVariantAnimation

        self._widget = widget
        self._host = host or widget.parentWidget()
        self._halo = _Halo(self._host)
        self._halo.hide()
        self.set_color(color)
        self._running = False
        self._anim = QVariantAnimation(widget)
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(period_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._apply)

    def set_color(self, color) -> None:
        from PyQt6.QtGui import QColor

        self._halo.color = QColor(color).lighter(130)
        self._halo.update()

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._halo.show()
        self._anim.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._anim.stop()
        self._halo.hide()

    def _apply(self, value) -> None:
        if not self._running:
            return
        from PyQt6.QtCore import QPoint, QRect

        top_left = self._widget.mapTo(self._host, QPoint(0, 0))
        spread = _Halo.SPREAD
        self._halo.setGeometry(QRect(top_left, self._widget.size()).adjusted(-spread, -spread, spread, spread))
        self._halo.stackUnder(self._widget) if self._widget.parentWidget() is self._host else self._halo.lower()
        self._halo.strength = 0.35 + 0.65 * float(value)
        self._halo.update()
