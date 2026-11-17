from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image
from core.imgops import gaussian_blur, resize, sobel


@dataclass
class NormalMapOptions:
    strength: float = 1.0
    invert_y: bool = False
    pre_blur_radius: int = 0
    seamless: bool = True
    multi_frequency: bool = False
    macro_strength: float = 1.0
    medium_strength: float = 1.0
    micro_strength: float = 1.0
    inject_albedo: bool = False
    albedo_strength: float = 0.5
    albedo_source: Image.Image | np.ndarray | None = None


_REFERENCE_DIM = 64.0


def _macro_kernel(h: int, w: int) -> int:
    return max(9, int(min(h, w) * 0.04) * 2 + 1)


def _medium_kernel(h: int, w: int) -> int:
    return max(3, int(min(h, w) * 0.01) * 2 + 1)


def generate_normal_map(height: np.ndarray, options: NormalMapOptions | None = None) -> np.ndarray:
    options = options or NormalMapOptions()
    working = height.astype(np.float32)
    h, w = working.shape

    margin = 0
    if options.seamless:
        margin = max(0, options.pre_blur_radius) + 3
        if options.multi_frequency:
            margin += max(_macro_kernel(h, w), _medium_kernel(h, w)) // 2
        working = np.pad(working, margin, mode="wrap")

    if options.pre_blur_radius > 0:
        k = options.pre_blur_radius * 2 + 1
        working = gaussian_blur(working, k)

    scale = options.strength * (max(h, w) / _REFERENCE_DIM)

    if options.multi_frequency:
        k_macro = _macro_kernel(h, w)
        h_macro = gaussian_blur(working, k_macro)
        gx_macro = sobel(h_macro, 1, 0) * scale * options.macro_strength
        gy_macro = sobel(h_macro, 0, 1) * scale * options.macro_strength

        k_med = _medium_kernel(h, w)
        h_med = gaussian_blur(working, k_med)
        gx_med = sobel(h_med - h_macro, 1, 0) * scale * options.medium_strength
        gy_med = sobel(h_med - h_macro, 0, 1) * scale * options.medium_strength

        h_micro = working - h_med
        gx_micro = sobel(h_micro, 1, 0) * scale * options.micro_strength
        gy_micro = sobel(h_micro, 0, 1) * scale * options.micro_strength

        gx = gx_macro + gx_med + gx_micro
        gy = gy_macro + gy_med + gy_micro
    else:
        gx = sobel(working, 1, 0) * scale
        gy = sobel(working, 0, 1) * scale

    if options.inject_albedo and options.albedo_source is not None and options.albedo_strength > 1e-4:
        alb = options.albedo_source
        if isinstance(alb, Image.Image):
            alb_arr = np.asarray(alb.convert("L"), dtype=np.float32) / 255.0
        elif alb.ndim == 3:
            alb_arr = (0.2126 * alb[..., 0] + 0.7152 * alb[..., 1] + 0.0722 * alb[..., 2]).astype(np.float32) / 255.0
        else:
            alb_arr = alb.astype(np.float32) / 255.0

        if alb_arr.shape[0] != h or alb_arr.shape[1] != w:
            alb_arr = resize(alb_arr, (w, h), "linear")

        if margin:
            alb_arr = np.pad(alb_arr, margin, mode="wrap" if options.seamless else "reflect")

        alb_blur = gaussian_blur(alb_arr, 5)
        alb_hp = alb_arr - alb_blur
        gx += sobel(alb_hp, 1, 0) * scale * (options.albedo_strength * 1.5)
        gy += sobel(alb_hp, 0, 1) * scale * (options.albedo_strength * 1.5)

    if options.invert_y:
        gy = -gy

    nz = np.ones_like(working)
    normal = np.stack([-gx, -gy, nz], axis=-1)
    length = np.linalg.norm(normal, axis=-1, keepdims=True)
    normal = normal / np.maximum(length, 1e-8)

    if margin:
        normal = normal[margin : margin + h, margin : margin + w]

    return (normal * 0.5 + 0.5).astype(np.float32)


def to_image(normal: np.ndarray) -> Image.Image:
    arr = (np.clip(normal, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def save_normal_map(normal: np.ndarray, path: str) -> None:
    to_image(normal).save(path)
