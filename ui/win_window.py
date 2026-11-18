from __future__ import annotations

import ctypes
import sys
import uuid

_IS_WINDOWS = sys.platform == "win32"

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_MAINWINDOW = 2


def _hwnd(widget) -> int:
    return int(widget.winId())


def _set_dwm_int(hwnd: int, attribute: int, value: int) -> bool:
    data = ctypes.c_int(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd), ctypes.c_uint(attribute), ctypes.byref(data), ctypes.sizeof(data)
    )
    return result == 0


def apply_title_bar_theme(widget, dark: bool) -> None:
    if not _IS_WINDOWS:
        return
    try:
        hwnd = _hwnd(widget)
        if not _set_dwm_int(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark)):
            _set_dwm_int(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, int(dark))
        _set_dwm_int(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_MAINWINDOW)
    except (AttributeError, OSError):
        pass


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_string(cls, text: str) -> "_GUID":
        u = uuid.UUID(text)
        guid = cls()
        guid.Data1, guid.Data2, guid.Data3 = u.fields[0], u.fields[1], u.fields[2]
        guid.Data4[:] = u.bytes[8:]
        return guid


_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
_IID_ITASKBAR_LIST3 = "{ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf}"
_CLSCTX_INPROC_SERVER = 1

_SLOT_HR_INIT = 3
_SLOT_SET_PROGRESS_STATE = 10

TBPF_NOPROGRESS = 0x0
TBPF_INDETERMINATE = 0x1


class TaskbarProgress:
    def __init__(self, widget):
        self._widget = widget
        self._taskbar = None
        if not _IS_WINDOWS:
            return
        try:
            ctypes.windll.ole32.CoInitialize(None)
            ptr = ctypes.c_void_p()
            clsid = _GUID.from_string(_CLSID_TASKBAR_LIST)
            iid = _GUID.from_string(_IID_ITASKBAR_LIST3)
            hr = ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(clsid), None, _CLSCTX_INPROC_SERVER, ctypes.byref(iid), ctypes.byref(ptr)
            )
            if hr == 0 and ptr.value:
                self._taskbar = ptr
                self._call(_SLOT_HR_INIT, [])
        except (AttributeError, OSError):
            self._taskbar = None

    def _call(self, slot: int, args: list, argtypes: list | None = None) -> None:
        vtable = ctypes.cast(self._taskbar, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *(argtypes or []))
        prototype(vtable[slot])(self._taskbar, *args)

    def _set_state(self, state: int) -> None:
        if self._taskbar is None:
            return
        try:
            self._call(_SLOT_SET_PROGRESS_STATE, [ctypes.c_void_p(_hwnd(self._widget)), state],
                       [ctypes.c_void_p, ctypes.c_int])
        except OSError:
            pass

    def set_busy(self, busy: bool) -> None:
        self._set_state(TBPF_INDETERMINATE if busy else TBPF_NOPROGRESS)


# ---------------------------------------------------------------------------
# Frameless main window
#
# The same technique as PyQt-Frameless-Window (zhiyiYo): the window keeps its
# native styles (WS_THICKFRAME, WS_CAPTION, ...) so Windows still gives it a
# shadow, Aero Snap, the minimize/maximize animations and the system menu, but
# WM_NCCALCSIZE hands the whole window to the client area, so no title bar or
# frame is drawn. WM_NCHITTEST then tells Windows which parts of our own
# widgets act as the resize border, the caption (drag, double-click to
# maximize) and the maximize button (Windows 11 Snap Layouts).
# ---------------------------------------------------------------------------

_RESIZE_BORDER = 5

_GWL_STYLE = -16
_WS_SYSMENU = 0x00080000
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_SWP_FRAME = 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010  # FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER|NOACTIVATE

_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_WM_NCMOUSEMOVE = 0x00A0
_WM_NCLBUTTONDOWN = 0x00A1
_WM_NCLBUTTONUP = 0x00A2
_WM_NCLBUTTONDBLCLK = 0x00A3
_WM_NCMOUSELEAVE = 0x02A2
_WM_MOUSEMOVE = 0x0200

_HTCLIENT = 1
_HTCAPTION = 2
_HTMAXBUTTON = 9
_HTLEFT, _HTRIGHT, _HTTOP, _HTTOPLEFT, _HTTOPRIGHT = 10, 11, 12, 13, 14
_HTBOTTOM, _HTBOTTOMLEFT, _HTBOTTOMRIGHT = 15, 16, 17

_SM_CXSIZEFRAME, _SM_CYSIZEFRAME, _SM_CXPADDEDBORDER = 32, 33, 92
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2

_ABM_GETSTATE, _ABM_GETTASKBARPOS = 4, 5
_ABS_AUTOHIDE = 1
_ABE_LEFT, _ABE_TOP, _ABE_RIGHT, _ABE_BOTTOM = 0, 1, 2, 3


def _win_types():
    from ctypes import wintypes

    class MARGINS(ctypes.Structure):
        _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                    ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                    ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                    ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]

    return wintypes, MARGINS, NCCALCSIZE_PARAMS, APPBARDATA


def _frame_thickness(hwnd: int) -> tuple[int, int]:
    user32 = ctypes.windll.user32
    try:
        dpi = user32.GetDpiForWindow(ctypes.c_void_p(hwnd))
        pad = user32.GetSystemMetricsForDpi(_SM_CXPADDEDBORDER, dpi)
        return (user32.GetSystemMetricsForDpi(_SM_CXSIZEFRAME, dpi) + pad,
                user32.GetSystemMetricsForDpi(_SM_CYSIZEFRAME, dpi) + pad)
    except AttributeError:  # before Windows 10 1607
        pad = user32.GetSystemMetrics(_SM_CXPADDEDBORDER)
        return (user32.GetSystemMetrics(_SM_CXSIZEFRAME) + pad,
                user32.GetSystemMetrics(_SM_CYSIZEFRAME) + pad)


def _autohide_taskbar_edge() -> int | None:
    """Edge of an auto-hiding taskbar, which a maximized window must not cover
    completely or the taskbar can never be brought back with the mouse."""
    _wt, _m, _n, APPBARDATA = _win_types()
    data = APPBARDATA()
    data.cbSize = ctypes.sizeof(APPBARDATA)
    shell32 = ctypes.windll.shell32
    if not shell32.SHAppBarMessage(_ABM_GETSTATE, ctypes.byref(data)) & _ABS_AUTOHIDE:
        return None
    shell32.SHAppBarMessage(_ABM_GETTASKBARPOS, ctypes.byref(data))
    return data.uEdge


class FramelessWindow:
    """Make a QMainWindow frameless while keeping native Windows behaviour.

    `drag_areas` are widgets that move the window like a title bar (their
    buttons and other controls stay clickable). `max_button` is reported to
    Windows as the maximize button so Windows 11 shows Snap Layouts over it.
    """

    def __init__(self, window):
        from PyQt6.QtCore import Qt

        self._window = window
        self.drag_areas: list = []
        self.max_button = None
        self._styled = False
        window.setWindowFlags(window.windowFlags() | Qt.WindowType.FramelessWindowHint)

    # Called from the window's showEvent: the native handle exists by then.
    def apply_native_style(self) -> None:
        if not _IS_WINDOWS or self._styled:
            return
        self._styled = True
        try:
            _wt, MARGINS, _n, _a = _win_types()
            hwnd = _hwnd(self._window)
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.restype = ctypes.c_long
            style = user32.GetWindowLongW(ctypes.c_void_p(hwnd), _GWL_STYLE)
            style |= _WS_CAPTION | _WS_THICKFRAME | _WS_SYSMENU | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX
            user32.SetWindowLongW(ctypes.c_void_p(hwnd), _GWL_STYLE, ctypes.c_long(style))
            margins = MARGINS(1, 1, 1, 1)  # gives the window its DWM shadow
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(ctypes.c_void_p(hwnd), ctypes.byref(margins))
            _set_dwm_int(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
            user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, _SWP_FRAME)
        except (AttributeError, OSError):
            pass

    # -- hit testing -----------------------------------------------------

    def _is_drag_area(self, widget) -> bool:
        from PyQt6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QSlider

        interactive = (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QSlider)
        while widget is not None and widget is not self._window:
            if isinstance(widget, interactive):
                return False
            if widget in self.drag_areas:
                return True
            widget = widget.parentWidget()
        return False

    def _hit_test(self) -> int:
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QApplication

        window = self._window
        global_pos = QCursor.pos()
        pos = window.mapFromGlobal(global_pos)
        w, h = window.width(), window.height()
        if not (window.isMaximized() or window.isFullScreen()):
            b = _RESIZE_BORDER
            left, right = pos.x() < b, pos.x() >= w - b
            top, bottom = pos.y() < b, pos.y() >= h - b
            if top and left:
                return _HTTOPLEFT
            if top and right:
                return _HTTOPRIGHT
            if bottom and left:
                return _HTBOTTOMLEFT
            if bottom and right:
                return _HTBOTTOMRIGHT
            if left:
                return _HTLEFT
            if right:
                return _HTRIGHT
            if top:
                return _HTTOP
            if bottom:
                return _HTBOTTOM
        target = QApplication.widgetAt(global_pos)
        button = self.max_button
        if button is not None and button.isVisible():
            if button.rect().contains(button.mapFromGlobal(global_pos)):
                return _HTMAXBUTTON
        if target is not None and self._is_drag_area(target):
            return _HTCAPTION
        return _HTCLIENT

    # -- native events ---------------------------------------------------

    def _set_max_hover(self, hover: bool, pressed: bool | None = None) -> None:
        button = self.max_button
        if button is not None:
            button.set_native_state(hover, pressed)

    def native_event(self, event_type, message):
        """Call from QMainWindow.nativeEvent; returns (handled, result)."""
        if not _IS_WINDOWS or bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        wintypes, _m, NCCALCSIZE_PARAMS, _a = _win_types()
        msg = wintypes.MSG.from_address(int(message))
        kind = msg.message

        if kind == _WM_NCCALCSIZE:
            if msg.wParam:
                rect = NCCALCSIZE_PARAMS.from_address(msg.lParam).rgrc[0]
            else:
                rect = wintypes.RECT.from_address(msg.lParam)
            if ctypes.windll.user32.IsZoomed(ctypes.c_void_p(msg.hWnd)):
                # A maximized window hangs its frame off the screen; keep the
                # client area on it.
                tx, ty = _frame_thickness(msg.hWnd or 0)
                rect.left += tx
                rect.top += ty
                rect.right -= tx
                rect.bottom -= ty
                edge = _autohide_taskbar_edge()
                if edge == _ABE_BOTTOM:
                    rect.bottom -= 2
                elif edge == _ABE_TOP:
                    rect.top += 2
                elif edge == _ABE_LEFT:
                    rect.left += 2
                elif edge == _ABE_RIGHT:
                    rect.right -= 2
            return True, 0

        if kind == _WM_NCHITTEST:
            return True, self._hit_test()

        # The maximize button gets non-client messages while it reports
        # HTMAXBUTTON; drive its hover/pressed look and click from them.
        if kind == _WM_NCMOUSEMOVE:
            self._set_max_hover(msg.wParam == _HTMAXBUTTON)
            return False, 0
        if kind in (_WM_NCMOUSELEAVE, _WM_MOUSEMOVE):
            self._set_max_hover(False, False)
            return False, 0
        if kind in (_WM_NCLBUTTONDOWN, _WM_NCLBUTTONDBLCLK) and msg.wParam == _HTMAXBUTTON:
            self._set_max_hover(True, True)
            return True, 0
        if kind == _WM_NCLBUTTONUP and msg.wParam == _HTMAXBUTTON:
            self._set_max_hover(True, False)
            if self.max_button is not None:
                self.max_button.click()
            return True, 0
        return False, 0
