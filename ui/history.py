"""Undo / redo for the material being edited.

A snapshot holds everything the user can change: the imported and generated
images, every panel's settings and the last saved Adjustment state per map.
Images are never modified in place (each change stores a new image object), so
a snapshot only keeps references and costs almost no memory.

Changes are recorded after they settle: any edit restarts a short timer, and
when it fires the new state is compared with the last recorded one. A burst of
edits (dragging a knob, typing a number) therefore becomes a single undo step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

MAX_STEPS = 60
SETTLE_MS = 450


@dataclass
class Snapshot:
    source_images: dict
    generated_images: dict
    height_depth: Any
    panels: dict
    saved: dict
    label: str = ""
    current_map: Any = None

    def same_as(self, other: "Snapshot") -> bool:
        return (
            _same_images(self.source_images, other.source_images)
            and _same_images(self.generated_images, other.generated_images)
            and self.height_depth is other.height_depth
            and self.panels == other.panels
            and self.saved == other.saved
        )


def _same_images(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(a[k] is b[k] for k in a)


class History(QObject):
    changed = pyqtSignal()

    def __init__(self, capture: Callable[[], Optional[Snapshot]], restore: Callable[[Snapshot], None], parent=None):
        super().__init__(parent)
        self._capture = capture
        self._restore = restore
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        self._current: Optional[Snapshot] = None
        self._suspended = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SETTLE_MS)
        self._timer.timeout.connect(self.commit)

    def reset(self) -> None:
        """Forget the past, e.g. after New Project or Open Project."""
        self._timer.stop()
        self._undo.clear()
        self._redo.clear()
        self._current = self._capture()
        self.changed.emit()

    def touch(self) -> None:
        """Something changed; record it once edits settle."""
        if self._suspended:
            return
        self._timer.start()

    def commit(self) -> None:
        if self._suspended:
            return
        snap = self._capture()
        if snap is None:
            self._timer.start()
            return
        if self._current is None:
            self._current = snap
            return
        if snap.same_as(self._current):
            return
        self._undo.append(self._current)
        del self._undo[:-MAX_STEPS]
        self._redo.clear()
        self._current = snap
        self.changed.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        self.commit()
        if not self._undo:
            return False
        self._redo.append(self._current)
        self._apply(self._undo.pop())
        return True

    def redo(self) -> bool:
        self.commit()
        if not self._redo:
            return False
        self._undo.append(self._current)
        self._apply(self._redo.pop())
        return True

    def _apply(self, snap: Snapshot) -> None:
        self._timer.stop()
        self._suspended += 1
        try:
            self._restore(snap)
        finally:
            self._suspended -= 1
        self._timer.stop()
        self._current = self._capture() or snap
        self.changed.emit()
