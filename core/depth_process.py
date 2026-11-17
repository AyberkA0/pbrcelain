"""Run the depth model in a separate process so it can be stopped at once.

A thread cannot be killed: a cancelled depth run used to keep going until the
model finished its current step, which on a large image or a slow device can
take a long time. Here the model lives in a child process. Cancel kills that
process outright; the next run starts a fresh one and loads the model again.

RemoteDepthEstimator has the same interface as DepthEstimator, so the workers
and the main window use it the same way.
"""

from __future__ import annotations

import multiprocessing
import threading
from typing import Callable, Optional

import numpy as np
from PIL import Image

from core.depth_models import DepthResult, InferenceCancelled, MODEL_CATALOG

ProgressCB = Optional[Callable[[str], None]]


def _serve(conn) -> None:
    """Child process: load the model on request and answer depth requests."""
    from core import ai_runtime

    ai_runtime.activate()
    from core.depth_models import DepthEstimator

    estimator = None

    def progress(text: str) -> None:
        conn.send(("progress", text))

    while True:
        try:
            command, args = conn.recv()
        except (EOFError, OSError):
            return
        try:
            if command == "load":
                family, variant, device = args
                estimator = DepthEstimator(family, variant, device)
                estimator.load(progress_cb=progress)
                conn.send(("done", estimator.device))
            elif command == "infer":
                conn.send(("done", estimator.infer(args, progress_cb=progress)))
            elif command == "infer_tiled":
                image, kwargs = args
                result = estimator.infer_tiled(
                    image,
                    progress_cb=progress,
                    partial_cb=lambda depth: conn.send(("partial", depth)),
                    **kwargs,
                )
                conn.send(("done", result))
            elif command == "quit":
                return
        except Exception as exc:  # reported to the app, which shows it
            conn.send(("error", str(exc)))


class RemoteDepthEstimator:
    def __init__(self, family: str, variant: str, device: str = "auto"):
        if family not in MODEL_CATALOG or variant not in MODEL_CATALOG[family]:
            raise ValueError(f"Unknown model {family}/{variant}")
        self.family = family
        self.variant = variant
        self.checkpoint = MODEL_CATALOG[family][variant]
        self.requested_device = device
        self.device = device
        self._process = None
        self._conn = None
        self._loaded = False
        self._killed = False
        self._lock = threading.Lock()

    def key(self) -> str:
        return f"{self.checkpoint}|{self.device}"

    def is_loaded(self) -> bool:
        return self._loaded and self._process is not None and self._process.is_alive()

    # -- process control -------------------------------------------------

    def _start(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent_conn, child_conn = context.Pipe()
        self._process = context.Process(target=_serve, args=(child_conn,), daemon=True, name="pbrcelain-depth")
        self._process.start()
        child_conn.close()
        self._conn = parent_conn
        self._killed = False

    def kill(self) -> None:
        """Stop whatever the model is doing, immediately."""
        self._killed = True
        self._loaded = False
        process = self._process
        if process is not None and process.is_alive():
            process.kill()
            process.join(2)
        self._process = None
        conn, self._conn = self._conn, None
        # A request waiting on the connection sees it close (the other end died)
        # and closes it itself; only close it here when nothing is waiting.
        if conn is not None and self._lock.acquire(blocking=False):
            try:
                conn.close()
            finally:
                self._lock.release()

    def unload(self) -> None:
        if self._process is not None and self._process.is_alive():
            try:
                with self._lock:
                    self._conn.send(("quit", None))
                self._process.join(2)
            except (OSError, ValueError):
                pass
        self.kill()
        self._killed = False

    # -- requests --------------------------------------------------------

    def _request(self, command: str, args, progress_cb: ProgressCB = None, partial_cb=None):
        conn = self._conn
        if conn is None:
            raise InferenceCancelled()
        with self._lock:
            conn.send((command, args))
            while True:
                try:
                    kind, payload = conn.recv()
                except (EOFError, OSError):
                    try:
                        conn.close()
                    except OSError:
                        pass
                    if self._killed:
                        raise InferenceCancelled() from None
                    self._loaded = False
                    raise RuntimeError("The depth model process stopped unexpectedly.") from None
                if kind == "progress":
                    if progress_cb:
                        progress_cb(payload)
                elif kind == "partial":
                    if partial_cb:
                        partial_cb(payload)
                elif kind == "error":
                    raise RuntimeError(payload)
                else:
                    return payload

    def load(self, progress_cb: ProgressCB = None) -> None:
        if self._process is None or not self._process.is_alive():
            self._start()
        self.device = self._request("load", (self.family, self.variant, self.requested_device), progress_cb)
        self._loaded = True

    def infer(self, image: Image.Image, progress_cb: ProgressCB = None) -> DepthResult:
        return self._request("infer", image, progress_cb)

    def infer_tiled(
        self,
        image: Image.Image,
        tile_size: int = 768,
        overlap_pct: float = 25.0,
        progress_cb: ProgressCB = None,
        partial_cb: Optional[Callable[[np.ndarray], None]] = None,
        is_cancelled=None,
        batch_size: int = 1,
    ) -> DepthResult:
        kwargs = {"tile_size": tile_size, "overlap_pct": overlap_pct, "batch_size": batch_size}
        return self._request("infer_tiled", (image, kwargs), progress_cb, partial_cb)
