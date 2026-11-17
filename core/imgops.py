"""The handful of image operations the app needs, in pure numpy.

These replace OpenCV (which ships ~120 MB of video codecs the app never uses)
and follow its conventions exactly, so results match the previous output:

- borders are BORDER_REFLECT_101 ("gfedcb|abcdefgh|gfedcba"), numpy's "reflect";
- Gaussian kernels use OpenCV's sigma-from-size rule and its fixed small kernels;
- resizing uses OpenCV's pixel-centre mapping for INTER_LINEAR and INTER_AREA;
- the elliptical structuring element is built with OpenCV's rounding.

"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

_SMALL_GAUSSIAN = {
    1: [1.0],
    3: [0.25, 0.5, 0.25],
    5: [0.0625, 0.25, 0.375, 0.25, 0.0625],
    7: [0.03125, 0.109375, 0.21875, 0.28125, 0.21875, 0.109375, 0.03125],
    9: [x / 256.0 for x in (4, 13, 30, 51, 60, 51, 30, 13, 4)],
}

# Kernels at least this long are applied through an FFT instead of shifted sums.
_FFT_MIN_KERNEL = 41
# Images at least this large are filtered in strips on several threads; numpy
# releases the GIL inside FFTs and array arithmetic, and each strip is computed
# exactly as the whole image would be, so results do not change.
_PARALLEL_MIN_PIXELS = 1 << 20
_WORKERS = max(1, min(8, os.cpu_count() or 1))
_pool: ThreadPoolExecutor | None = None


def _strips(fn, arr: np.ndarray, axis: int) -> np.ndarray:
    """Apply `fn` (which works along `axis`) to strips cut across the other axis."""
    other = 1 - axis
    if _WORKERS == 1 or arr.shape[0] * arr.shape[1] < _PARALLEL_MIN_PIXELS or arr.shape[other] < 2 * _WORKERS:
        return fn(arr)
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(_WORKERS, thread_name_prefix="imgops")
    bounds = np.linspace(0, arr.shape[other], 2 * _WORKERS + 1).astype(int)

    def part(i: int) -> np.ndarray:
        index = [slice(None)] * arr.ndim
        index[other] = slice(bounds[i], bounds[i + 1])
        return fn(arr[tuple(index)])

    return np.concatenate(list(_pool.map(part, range(len(bounds) - 1))), axis=other)


def gaussian_kernel(ksize: int, sigma: float) -> np.ndarray:
    if sigma <= 0 and ksize in _SMALL_GAUSSIAN:
        return np.asarray(_SMALL_GAUSSIAN[ksize], dtype=np.float64)
    if sigma <= 0:
        sigma = 0.3 * ((ksize - 1) * 0.5 - 1) + 0.8
    x = np.arange(ksize, dtype=np.float64) - (ksize - 1) * 0.5
    kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
    return kernel / kernel.sum()


def _ksize_from_sigma(sigma: float) -> int:
    return int(round(sigma * 4 * 2 + 1)) | 1


def _convolve_axis(arr: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    """Correlate `arr` with a centred 1-D kernel along `axis`, REFLECT_101 border."""
    k = kernel.shape[0]
    r = k // 2
    if k == 1:
        return arr * kernel[0]
    pad = [(0, 0)] * arr.ndim
    pad[axis] = (r, r)
    padded = np.pad(arr, pad, mode="reflect")
    n = arr.shape[axis]

    if k < _FFT_MIN_KERNEL:
        out = np.zeros(arr.shape, dtype=arr.dtype)
        index = [slice(None)] * arr.ndim
        for i, weight in enumerate(kernel):
            if weight == 0.0:
                continue
            index[axis] = slice(i, i + n)
            out += arr.dtype.type(weight) * padded[tuple(index)]
        return out

    length = padded.shape[axis]
    size = _fast_length(length + k - 1)
    spectrum = np.fft.rfft(padded, n=size, axis=axis)
    kspec = np.fft.rfft(kernel[::-1].astype(arr.dtype), n=size)
    shape = [1] * arr.ndim
    shape[axis] = kspec.shape[0]
    spectrum *= kspec.reshape(shape)
    full = np.fft.irfft(spectrum, n=size, axis=axis)
    index = [slice(None)] * arr.ndim
    index[axis] = slice(k - 1, k - 1 + n)
    return full[tuple(index)].astype(arr.dtype, copy=False)


def _fast_length(n: int) -> int:
    """Smallest length >= n whose only prime factors are 2, 3 and 5."""
    best = 1 << int(math.ceil(math.log2(max(n, 1))))
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def _separable(arr: np.ndarray, kx: np.ndarray, ky: np.ndarray) -> np.ndarray:
    src = np.asarray(arr)
    dtype = np.float64 if src.dtype == np.float64 else np.float32
    work = src.astype(dtype, copy=False)
    out = _strips(lambda a: _convolve_axis(a, ky, 0), work, 0)
    out = _strips(lambda a: _convolve_axis(a, kx, 1), out, 1)
    return out.astype(src.dtype if src.dtype.kind == "f" else np.float32, copy=False)


def gaussian_blur(arr: np.ndarray, ksize: int = 0, sigma: float = 0.0) -> np.ndarray:
    """cv2.GaussianBlur(arr, (ksize, ksize), sigma). ksize 0 derives it from sigma."""
    if ksize <= 0:
        ksize = _ksize_from_sigma(sigma)
    kernel = gaussian_kernel(ksize, sigma)
    return _separable(arr, kernel, kernel)


def box_filter(arr: np.ndarray, ksize: int) -> np.ndarray:
    """cv2.boxFilter(arr, -1, (ksize, ksize)) with normalisation."""
    src = np.asarray(arr)
    out = src.astype(np.float64)
    r = ksize // 2
    for axis in (0, 1):
        def running_mean(a: np.ndarray, axis: int = axis) -> np.ndarray:
            pad = [(0, 0)] * a.ndim
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad, mode="reflect" if a.shape[axis] > 1 else "edge"), axis=axis)
            n = a.shape[axis]
            hi = [slice(None)] * a.ndim
            lo = [slice(None)] * a.ndim
            hi[axis] = slice(ksize, ksize + n)
            lo[axis] = slice(0, n)
            return (c[tuple(hi)] - c[tuple(lo)]) / ksize

        out = _strips(running_mean, out, axis)
    return out.astype(src.dtype if src.dtype.kind == "f" else np.float32)


def sobel(arr: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """cv2.Sobel(arr, CV_32F, dx, dy, ksize=3) for first derivatives."""
    deriv = np.array([-1.0, 0.0, 1.0])
    smooth = np.array([1.0, 2.0, 1.0])
    kx, ky = (deriv, smooth) if dx else (smooth, deriv)
    return _separable(np.asarray(arr, dtype=np.float32), kx, ky).astype(np.float32)


def rgb_to_gray(arr: np.ndarray) -> np.ndarray:
    """cv2.cvtColor(arr, COLOR_RGB2GRAY) for float images."""
    a = np.asarray(arr, dtype=np.float32)
    return (a[..., 0] * np.float32(0.299) + a[..., 1] * np.float32(0.587) + a[..., 2] * np.float32(0.114)).astype(np.float32)


# --- resizing -----------------------------------------------------------------

def _linear_weights(dst: int, src: int, area_style: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    scale = src / dst
    d = np.arange(dst, dtype=np.float64)
    if area_style:
        s = np.floor(d * scale)
        f = (d + 1) - (s + 1) / scale
        f = np.where(f <= 0, 0.0, f - np.floor(f))
    else:
        pos = (d + 0.5) * scale - 0.5
        s = np.floor(pos)
        f = pos - s
    s = s.astype(np.int64)
    i0 = np.clip(s, 0, src - 1)
    i1 = np.clip(s + 1, 0, src - 1)
    f = np.where(s < 0, 0.0, f)
    f = np.where(s >= src - 1, 0.0, f)
    return i0, i1, f


def _area_matrix(dst: int, src: int) -> np.ndarray:
    """Coverage weights of each source pixel in each destination pixel."""
    scale = src / dst
    d = np.arange(dst, dtype=np.float64)[:, None]
    s = np.arange(src, dtype=np.float64)[None, :]
    overlap = np.clip(np.minimum((d + 1) * scale, s + 1) - np.maximum(d * scale, s), 0.0, None)
    overlap[overlap < 1e-12] = 0.0
    return overlap / overlap.sum(axis=1, keepdims=True)


def _resize_axis(arr: np.ndarray, dst: int, axis: int, method: str) -> np.ndarray:
    src = arr.shape[axis]
    if dst == src:
        return arr
    if method == "area":
        m = _area_matrix(dst, src)
        width = int(np.count_nonzero(m, axis=1).max())
        first = np.argmax(m > 0, axis=1)
        out = None
        for j in range(width):
            idx = np.minimum(first + j, src - 1)
            weight = m[np.arange(dst), idx] * ((first + j) < src)
            shape = [1] * arr.ndim
            shape[axis] = dst
            term = np.take(arr, idx, axis=axis) * weight.reshape(shape)
            out = term if out is None else out + term
        return out
    i0, i1, f = _linear_weights(dst, src, area_style=(method == "area-linear"))
    a0 = np.take(arr, i0, axis=axis)
    a1 = np.take(arr, i1, axis=axis)
    shape = [1] * arr.ndim
    shape[axis] = dst
    f = f.reshape(shape)
    return a0 * (1.0 - f) + a1 * f


def resize(arr: np.ndarray, size: tuple[int, int], mode: str = "linear") -> np.ndarray:
    """cv2.resize(arr, (width, height), interpolation=INTER_LINEAR / INTER_AREA)."""
    width, height = size
    src = np.asarray(arr)
    work = src.astype(np.float64, copy=False)
    h, w = work.shape[:2]
    if mode == "area":
        # OpenCV averages pixel areas only when shrinking both axes; otherwise
        # it interpolates with its area-style coefficients.
        method = "area" if (w >= width and h >= height) else "area-linear"
    else:
        method = "linear"
    out = _resize_axis(_resize_axis(work, height, 0, method), width, 1, method)
    return out.astype(src.dtype if src.dtype.kind == "f" else np.float32, copy=False)


# --- morphology -----------------------------------------------------------------

def ellipse_element(ksize: int) -> np.ndarray:
    """cv2.getStructuringElement(MORPH_ELLIPSE, (ksize, ksize))."""
    r = ksize // 2
    c = ksize // 2
    inv_r2 = 1.0 / (r * r) if r else 0.0
    se = np.zeros((ksize, ksize), dtype=np.uint8)
    for i in range(ksize):
        dy = i - r
        if abs(dy) <= r:
            dx = int(round(c * math.sqrt((r * r - dy * dy) * inv_r2))) if r else 0
            j1 = max(c - dx, 0)
            j2 = min(c + dx + 1, ksize)
            se[i, j1:j2] = 1
    return se


def _morph(arr: np.ndarray, se: np.ndarray, op) -> np.ndarray:
    """Erosion (op=np.minimum) or dilation (np.maximum) with a symmetric element.

    Pixels outside the image are ignored, as in OpenCV. Each element row is a
    centred horizontal run; runs are grown two pixels at a time from the
    previous width, so the cost is about one pass per element row.
    """
    k = se.shape[0]
    r = k // 2
    fill = np.float32(np.inf if op is np.minimum else -np.inf)
    h, w = arr.shape
    half = [int(np.flatnonzero(row).max()) - r if row.any() else -1 for row in se]
    reach = max(half)
    base = np.full((h + 2 * r, w + 2 * reach), fill, dtype=np.float32)
    base[r:r + h, reach:reach + w] = arr
    out = np.full((h, w), fill, dtype=np.float32)
    run = base.copy()
    width = 0
    for target in sorted(set(x for x in half if x >= 0)):
        while width < target:
            grown = run.copy()
            op(grown[:, 1:], run[:, :-1], out=grown[:, 1:])
            op(grown[:, :-1], run[:, 1:], out=grown[:, :-1])
            run = grown
            width += 1
        view = run[:, reach:reach + w]
        for i in range(k):
            if half[i] == target:
                op(out, view[i:i + h], out=out)
    return out


def _morph_strips(arr: np.ndarray, se: np.ndarray, op) -> np.ndarray:
    """_morph on horizontal strips in parallel. Each strip carries the element
    radius of extra rows from its neighbours, so every kept row sees exactly
    the rows it would see in the whole image."""
    h = arr.shape[0]
    r = se.shape[0] // 2
    if _WORKERS == 1 or arr.size < _PARALLEL_MIN_PIXELS or h < 4 * _WORKERS:
        return _morph(arr, se, op)
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(_WORKERS, thread_name_prefix="imgops")
    bounds = np.linspace(0, h, 2 * _WORKERS + 1).astype(int)

    def part(i: int) -> np.ndarray:
        s0, s1 = int(bounds[i]), int(bounds[i + 1])
        a0, a1 = max(0, s0 - r), min(h, s1 + r)
        return _morph(arr[a0:a1], se, op)[s0 - a0:s1 - a0]

    return np.concatenate(list(_pool.map(part, range(len(bounds) - 1))), axis=0)


def _erode(arr: np.ndarray, se: np.ndarray) -> np.ndarray:
    return _morph_strips(arr, se, np.minimum)


def _dilate(arr: np.ndarray, se: np.ndarray) -> np.ndarray:
    return _morph_strips(arr, se, np.maximum)


def tophat(arr: np.ndarray, se: np.ndarray) -> np.ndarray:
    """cv2.morphologyEx(arr, MORPH_TOPHAT, se): arr minus its opening."""
    a = np.asarray(arr, dtype=np.float32)
    return (a - _dilate(_erode(a, se), se)).astype(np.asarray(arr).dtype)


def blackhat(arr: np.ndarray, se: np.ndarray) -> np.ndarray:
    """cv2.morphologyEx(arr, MORPH_BLACKHAT, se): closing minus arr."""
    a = np.asarray(arr, dtype=np.float32)
    return (_erode(_dilate(a, se), se) - a).astype(np.asarray(arr).dtype)


# --- drawing ---------------------------------------------------------------------

def draw_line(img: np.ndarray, p0: tuple[int, int], p1: tuple[int, int], value: float) -> None:
    """cv2.line(img, p0, p1, value, thickness=1), 8-connected, in place."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x1 >= x0 else -1), (1 if y1 >= y0 else -1)
    h, w = img.shape[:2]
    if dx >= dy:
        for i in range(dx + 1):
            x = x0 + sx * i
            y = y0 + sy * int((i * dy + dx // 2) // dx) if dx else y0
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = value
    else:
        for i in range(dy + 1):
            y = y0 + sy * i
            x = x0 + sx * int((i * dx + dy // 2) // dy)
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = value
