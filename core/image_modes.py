"""Bit-depth safe conversions for map images.

Pillow's convert() clips 16-bit and float greyscale values instead of scaling them
(a 16-bit map turns white, a 0..1 float map turns black), so every place that
narrows a map's mode should go through these helpers.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# Greyscale modes holding 16-bit values: byte orders Pillow opens (macOS writes big-endian
# 16-bit TIFFs, which open as I;16B) and the 32-bit integer mode some files decode to.
GRAY16_MODES = ("I;16", "I;16B", "I;16L", "I;16N", "I")


def is_wide_gray(image: Image.Image) -> bool:
    """True for single-channel images with more than 8 bits (16-bit or float)."""
    return image.mode in GRAY16_MODES or image.mode == "F"


def to_unit_array(image: Image.Image) -> np.ndarray:
    """Greyscale image as float32 in 0..1, whatever its bit depth."""
    if image.mode in GRAY16_MODES:
        return (np.asarray(image, dtype=np.float32) / 65535.0).clip(0.0, 1.0)
    if image.mode == "F":
        return np.asarray(image, dtype=np.float32).clip(0.0, 1.0)
    return np.asarray(image.convert("L"), dtype=np.float32) / 255.0


def to_gray16(image: Image.Image) -> Image.Image:
    """16-bit greyscale (mode I;16) copy of a greyscale image of any depth."""
    if image.mode == "I;16":
        return image
    arr = (to_unit_array(image) * 65535.0).round().astype(np.uint16)
    return Image.fromarray(arr)


def to_gray8(image: Image.Image) -> Image.Image:
    """8-bit greyscale copy, scaling 16-bit and float maps instead of clipping them."""
    if is_wide_gray(image):
        arr = (to_unit_array(image) * 255.0).round().astype(np.uint8)
        return Image.fromarray(arr, mode="L")
    return image.convert("L")


def to_rgb8(image: Image.Image) -> Image.Image:
    """8-bit RGB copy; a 16-bit or float greyscale image is scaled first."""
    if is_wide_gray(image):
        return to_gray8(image).convert("RGB")
    return image.convert("RGB")


def prepare_source(image: Image.Image, keep_gray: bool) -> Image.Image:
    """Mode a loaded source image is kept in.

    keep_gray: the slot holds a greyscale map (height, roughness), so 8-bit greyscale stays
    as it is and every wider greyscale (16-bit of any byte order, 32-bit, float) becomes
    16-bit I;16, which the app and the project file both handle. Other slots get 8-bit RGB.
    """
    if keep_gray:
        if image.mode == "L":
            return image
        if is_wide_gray(image):
            return to_gray16(image)
    return to_rgb8(image)
