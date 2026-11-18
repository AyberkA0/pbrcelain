from __future__ import annotations

from PyQt6.QtCore import QByteArray, QSettings
from PyQt6.QtWidgets import QMainWindow, QSplitter

_KEYS = ("window/geometry", "window/sidebarSplit", "window/previewSplit")

# The window opens at a wide 20:9 shape, about 70 % of the screen's width.
_ASPECT = 20 / 9
_WIDTH_SHARE = 0.70
_MAX_WIDTH = 1800


def fit_to_screen(window: QMainWindow, sidebar_splitter: QSplitter, preview_splitter: QSplitter,
                  sidebar_ratio: float, sidebar_min: int, sidebar_max: int) -> None:
    screen = window.screen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    w = min(int(avail.width() * _WIDTH_SHARE), _MAX_WIDTH)
    h = int(w / _ASPECT)
    if h > avail.height() * 0.9:
        h = int(avail.height() * 0.9)
        w = int(h * _ASPECT)
    minimum = window.minimumSizeHint()
    w, h = max(w, minimum.width()), max(h, minimum.height())
    window.setGeometry(avail.x() + (avail.width() - w) // 2, avail.y() + (avail.height() - h) // 2, w, h)

    side = max(sidebar_min, min(sidebar_max, int(w * sidebar_ratio)))
    sidebar_splitter.setSizes([side, w - side])
    preview_splitter.setSizes([600, 400])


def restore(window: QMainWindow, sidebar_splitter: QSplitter, preview_splitter: QSplitter) -> bool:
    """Restore the saved splitter positions. The window itself always opens at
    the default size from fit_to_screen()."""
    settings = QSettings()
    _geometry, sidebar, preview = (settings.value(k) for k in _KEYS)
    restored = False
    if isinstance(sidebar, QByteArray):
        restored = sidebar_splitter.restoreState(sidebar) or restored
    if isinstance(preview, QByteArray):
        restored = preview_splitter.restoreState(preview) or restored
    return restored


def save(window: QMainWindow, sidebar_splitter: QSplitter, preview_splitter: QSplitter) -> None:
    settings = QSettings()
    for key, value in zip(_KEYS, (window.saveGeometry(), sidebar_splitter.saveState(), preview_splitter.saveState())):
        settings.setValue(key, value)
