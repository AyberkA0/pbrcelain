"""Compare core.imgops against OpenCV (skipped when OpenCV is not installed).

Run:  python tests/test_imgops.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import imgops  # noqa: E402

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

RNG = np.random.default_rng(1234)
FAILS: list[str] = []
WORST: dict[str, float] = {}


def _field(h: int, w: int, channels: int = 0) -> np.ndarray:
    """Smooth-plus-noise test image in [0, 1], like a height map."""
    shape = (h, w) if not channels else (h, w, channels)
    base = RNG.random(shape).astype(np.float32)
    k = np.ones(9, np.float32) / 9
    smooth = base
    for axis in (0, 1):
        if smooth.shape[axis] >= k.size:
            smooth = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), axis, smooth)
    return (0.7 * smooth + 0.3 * base).astype(np.float32)


def check(name: str, ours: np.ndarray, ref: np.ndarray, tol: float) -> None:
    ours = np.asarray(ours, dtype=np.float64)
    ref = np.asarray(ref, dtype=np.float64)
    if ours.shape != ref.shape:
        FAILS.append(f"{name}: shape {ours.shape} != {ref.shape}")
        return
    err = float(np.max(np.abs(ours - ref))) if ours.size else 0.0
    WORST[name.split("[")[0]] = max(WORST.get(name.split("[")[0], 0.0), err)
    if err > tol:
        FAILS.append(f"{name}: max abs diff {err:.3g} > {tol}")


def main() -> int:
    if cv2 is None:
        print("OpenCV not installed; nothing to compare.")
        return 0

    sizes = [(64, 64), (97, 131), (256, 200), (1, 50), (40, 3)]
    for h, w in sizes:
        img = _field(h, w)
        for k in (3, 5, 7, 9, 11, 13, 21, 41, 63, 129):
            check(f"gaussian[{h}x{w},k{k}]", imgops.gaussian_blur(img, k), cv2.GaussianBlur(img, (k, k), 0), 2e-5)
        for sigma in (0.6, 1.3, 2.7, 6.0):
            check(f"gaussian_sigma[{h}x{w},s{sigma}]", imgops.gaussian_blur(img, 0, sigma), cv2.GaussianBlur(img, (0, 0), sigma), 2e-5)
            k = int(round(sigma * 3)) * 2 + 1
            check(f"gaussian_k_sigma[{h}x{w},k{k},s{sigma}]", imgops.gaussian_blur(img, k, sigma), cv2.GaussianBlur(img, (k, k), sigmaX=sigma, sigmaY=sigma), 2e-5)
        for k in (3, 5, 9, 21, 61):
            check(f"box[{h}x{w},k{k}]", imgops.box_filter(img, k), cv2.boxFilter(img, -1, (k, k)), 2e-5)
        for dx, dy in ((1, 0), (0, 1)):
            check(f"sobel[{h}x{w},{dx}{dy}]", imgops.sobel(img, dx, dy), cv2.Sobel(img, cv2.CV_32F, dx, dy, ksize=3), 1e-5)

    # Large enough to take the multi-threaded path.
    large = _field(1200, 1100)
    for k in (5, 21, 63, 151):
        check(f"gaussian_large[k{k}]", imgops.gaussian_blur(large, k), cv2.GaussianBlur(large, (k, k), 0), 2e-5)
    check("box_large[k41]", imgops.box_filter(large, 41), cv2.boxFilter(large, -1, (41, 41)), 2e-5)
    check("sobel_large", imgops.sobel(large, 1, 0), cv2.Sobel(large, cv2.CV_32F, 1, 0, ksize=3), 1e-5)
    for k in (5, 27, 51):
        se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        check(f"tophat_large[k{k}]", imgops.tophat(large, imgops.ellipse_element(k)), cv2.morphologyEx(large, cv2.MORPH_TOPHAT, se), 1e-6)
        check(f"blackhat_large[k{k}]", imgops.blackhat(large, imgops.ellipse_element(k)), cv2.morphologyEx(large, cv2.MORPH_BLACKHAT, se), 1e-6)
    large_rgb = _field(1100, 1000, 3)
    check("box_large_rgb[k21]", imgops.box_filter(large_rgb, 21), cv2.boxFilter(large_rgb, -1, (21, 21)), 2e-5)

    rgb = _field(53, 77, 3) * 255.0
    check("rgb_to_gray", imgops.rgb_to_gray(rgb), cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 1e-3)
    big = _field(120, 90, 3)
    check("gaussian_rgb", imgops.gaussian_blur(big, 5), cv2.GaussianBlur(big, (5, 5), 0), 2e-5)

    for (h, w), (nw, nh) in [
        ((100, 100), (50, 50)), ((100, 100), (37, 61)), ((97, 131), (40, 40)), ((518, 518), (1024, 1024)),
        ((64, 64), (200, 150)), ((300, 200), (300, 90)), ((90, 300), (120, 60)), ((1024, 768), (1024, 768)),
    ]:
        img = _field(h, w)
        check(f"resize_linear[{h}x{w}->{nw}x{nh}]", imgops.resize(img, (nw, nh), "linear"), cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR), 2e-5)
        check(f"resize_area[{h}x{w}->{nw}x{nh}]", imgops.resize(img, (nw, nh), "area"), cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA), 2e-5)
        rgbimg = _field(h, w, 3)
        check(f"resize_area_rgb[{h}x{w}->{nw}x{nh}]", imgops.resize(rgbimg, (nw, nh), "area"), cv2.resize(rgbimg, (nw, nh), interpolation=cv2.INTER_AREA), 2e-5)

    for k in (3, 5, 7, 9, 11, 15, 21, 25, 51, 103):
        check(f"ellipse[{k}]", imgops.ellipse_element(k), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)), 0)
    for h, w in ((64, 64), (130, 97), (300, 260)):
        img = _field(h, w)
        for k in (3, 5, 9, 15, 25, 51):
            se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            check(f"tophat[{h}x{w},k{k}]", imgops.tophat(img, imgops.ellipse_element(k)), cv2.morphologyEx(img, cv2.MORPH_TOPHAT, se), 1e-6)
            check(f"blackhat[{h}x{w},k{k}]", imgops.blackhat(img, imgops.ellipse_element(k)), cv2.morphologyEx(img, cv2.MORPH_BLACKHAT, se), 1e-6)

    for p0, p1 in (((5, 5), (60, 30)), ((60, 5), (5, 40)), ((10, 50), (10, 2)), ((3, 3), (40, 40)), ((0, 63), (63, 0)), ((7, 2), (50, 59))):
        a = np.zeros((64, 64), np.float32)
        b = np.zeros((64, 64), np.float32)
        imgops.draw_line(a, p0, p1, 255.0)
        cv2.line(b, p0, p1, 255.0, thickness=1)
        check(f"line[{p0}->{p1}]", a, b, 0)

    for name, err in sorted(WORST.items()):
        print(f"  {name:22} worst diff {err:.2e}")
    if FAILS:
        print(f"\n{len(FAILS)} mismatches:")
        for line in FAILS[:40]:
            print("  " + line)
        return 1
    print("\nAll operations match OpenCV.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
