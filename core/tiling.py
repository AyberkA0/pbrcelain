from __future__ import annotations

from typing import Callable

import numpy as np


def filter_wrapped(arr: np.ndarray, margin: int, fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    margin = int(margin)
    if margin <= 0:
        return fn(arr)
    pad = [(margin, margin), (margin, margin)] + [(0, 0)] * (arr.ndim - 2)
    out = fn(np.pad(arr, pad, mode="wrap"))
    return out[margin:-margin, margin:-margin]
