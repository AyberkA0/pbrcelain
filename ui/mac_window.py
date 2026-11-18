from __future__ import annotations

import ctypes
import ctypes.util
import sys

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtWidgets import QMainWindow, QWidget

# 1.3 times the native macOS title bar (28 px).
TITLE_BAR_HEIGHT = 36
# The window buttons as macOS lays them out: the close button 9 px from the
# left, each button 14 x 16 px, one every 20 px.
_NATIVE_BUTTONS_LEFT = 9
_NATIVE_BUTTON_WIDTH = 14
_NATIVE_BUTTON_HEIGHT = 16
_NATIVE_BUTTON_STEP = 20
# In the taller bar they are drawn a bit bigger and further from the edge.
WINDOW_BUTTONS_SCALE = 1.2
WINDOW_BUTTONS_LEFT = 14
# How much further right the row ends than macOS's own; the title icons next
# to it move by as much.
WINDOW_BUTTONS_SHIFT = round(
    WINDOW_BUTTONS_LEFT + (2 * _NATIVE_BUTTON_STEP + _NATIVE_BUTTON_WIDTH) * WINDOW_BUTTONS_SCALE
    - (_NATIVE_BUTTONS_LEFT + 2 * _NATIVE_BUTTON_STEP + _NATIVE_BUTTON_WIDTH)
)


def hide_title_bar(window: QMainWindow) -> None:
    window.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint, True)
    window.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint, True)
    window.setAttribute(Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea, False)


# -- window buttons --------------------------------------------------------------

class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


_objc = None


def _runtime():
    global _objc
    if _objc is None:
        lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        _objc = lib
    return _objc


def _send(receiver, selector: bytes, *args, restype=ctypes.c_void_p, argtypes=()):
    lib = _runtime()
    send = ctypes.cast(lib.objc_msgSend, ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return send(receiver, lib.sel_registerName(selector), *args)


def center_window_buttons(window: QWidget, bar_height: int = TITLE_BAR_HEIGHT) -> None:
    """Lay the close, minimize and zoom buttons out for our title bar, which is
    taller than macOS's: WINDOW_BUTTONS_SCALE times their size and spacing,
    starting WINDOW_BUTTONS_LEFT from the left and centred in the bar. Each
    button keeps its native bounds inside a bigger frame, so AppKit scales its
    drawing. macOS lays them out again after some changes (resizing, full
    screen), so this is called again after those."""
    if sys.platform != "darwin" or window.windowHandle() is None:
        return
    try:
        nswindow = _send(ctypes.c_void_p(int(window.winId())), b"window")
        if not nswindow:
            return
        # NSWindowCloseButton, MiniaturizeButton, ZoomButton
        buttons = [_send(nswindow, b"standardWindowButton:", kind, argtypes=(ctypes.c_long,)) for kind in (0, 1, 2)]
        if not all(buttons):
            return
        scale = WINDOW_BUTTONS_SCALE
        for index, button in enumerate(buttons):
            # Native size from constants: once AppKit resizes a scaled button,
            # its bounds no longer tell the native size.
            native = _CGSize(_NATIVE_BUTTON_WIDTH, _NATIVE_BUTTON_HEIGHT)
            frame = _send(button, b"frame", restype=_CGRect)
            container = _send(_send(button, b"superview"), b"frame", restype=_CGRect)
            width, height = native.width * scale, native.height * scale
            x = WINDOW_BUTTONS_LEFT + index * _NATIVE_BUTTON_STEP * scale
            # The container is not flipped: y counts up from its bottom edge,
            # and its top edge is the top of the window.
            y = container.size.height - (bar_height - height) / 2 - height
            target = _CGRect(_CGPoint(x, y), _CGSize(width, height))
            if any(abs(a - b) > 0.25 for a, b in (
                (frame.origin.x, x), (frame.origin.y, y), (frame.size.width, width), (frame.size.height, height)
            )):
                _send(button, b"setFrame:", target, restype=None, argtypes=(_CGRect,))
                _send(button, b"setBoundsSize:", native, restype=None, argtypes=(_CGSize,))
    except (OSError, AttributeError, ValueError):
        pass


# -- dragging ------------------------------------------------------------------

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
