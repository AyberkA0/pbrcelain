from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from ui.theme import PLATFORM_THEME

_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")


def _colors() -> tuple[str, str]:
    if PLATFORM_THEME == "mac":
        from ui import mac_theme

        t = mac_theme.tokens()
        return t["strong"], t["secondary"]
    if PLATFORM_THEME == "windows":
        from ui import windows_theme

        t = windows_theme.tokens()
        return t["text"], t.get("secondary", t["text"])
    return "#e6e6e6", "#7a7a7a"


def _pixmap(svg: str, color: str) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(svg.replace("currentColor", color).encode("utf-8"), "SVG")
    return pixmap


def themed_icon(name: str) -> QIcon:
    with open(os.path.join(_ICON_DIR, f"{name}.svg"), encoding="utf-8") as f:
        svg = f.read()
    normal, dim = _colors()
    icon = QIcon(_pixmap(svg, normal))
    disabled = _pixmap(svg, dim)
    faded = QPixmap(disabled.size())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faded)
    painter.setOpacity(0.45)
    painter.drawPixmap(0, 0, disabled)
    painter.end()
    icon.addPixmap(faded, QIcon.Mode.Disabled)
    return icon


def status_dot(color: str, filled: bool = True) -> QIcon:
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(4, 4, size - 8, size - 8)
    else:
        painter.setPen(QPen(QColor(color), 4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(6, 6, size - 12, size - 12)
    painter.end()
    icon = QIcon(pixmap)
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
    return icon
