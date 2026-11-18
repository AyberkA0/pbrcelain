from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtWidgets import QMainWindow, QWidget

TITLE_BAR_HEIGHT = 28


def hide_title_bar(window: QMainWindow) -> None:
    window.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint, True)
    window.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint, True)
    window.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)


class _DragArea(QObject):
    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self._offset: QPoint | None = None

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            window = obj.window()
            handle = window.windowHandle()
            # The system move follows the pointer by itself. Moving the window
            # from mouse events as well made two movers fight and the window
            # shake, so that is only the fallback when the system move can't start.
            if handle is not None and handle.startSystemMove():
                self._offset = None
            else:
                self._offset = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
            return True
        if etype == QEvent.Type.MouseMove and self._offset is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                obj.window().move(event.globalPosition().toPoint() - self._offset)
                return True
        if etype == QEvent.Type.MouseButtonRelease:
            self._offset = None
        if etype == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            window = obj.window()
            window.showNormal() if window.isMaximized() else window.showMaximized()
            return True
        return False


def install_drag_area(widget: QWidget) -> None:
    widget.installEventFilter(_DragArea(widget))
