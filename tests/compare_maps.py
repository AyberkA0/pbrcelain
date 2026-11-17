"""End-to-end map comparison: run every map generator over a set of option
combinations and either save the results (baseline) or compare against a saved
baseline. Used to check that replacing OpenCV did not change any output.

    python tests/compare_maps.py save  baseline.npz
    python tests/compare_maps.py check baseline.npz
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import replace

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ao_map import AOMapOptions, generate_ao_map  # noqa: E402
from core.curvature_map import generate_curvature_map  # noqa: E402
from core.height_map import (  # noqa: E402
    DETREND_HIGHPASS, DETREND_NONE, DETREND_PLANE, DETREND_QUADRATIC, HeightMapOptions,
    apply_force_seamless_blur, apply_seamless_corner_heal, apply_seamless_linear_mask,
    build_height_map, build_seamless_extended_tile, downsample_for_preview,
)
from core.normal_map import NormalMapOptions, generate_normal_map  # noqa: E402
from core.roughness_map import RoughnessMapOptions, generate_roughness_map  # noqa: E402


def _periodic(n: int, seed: int, beta: float = 1.6) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f = np.fft.fft2(rng.standard_normal((n, n)))
    k = np.sqrt(np.fft.fftfreq(n)[:, None] ** 2 + np.fft.fftfreq(n)[None, :] ** 2)
    k[0, 0] = 1
    h = np.real(np.fft.ifft2(f / k ** beta))
    return ((h - h.min()) / (h.max() - h.min())).astype(np.float32)


def scenarios():
    n = 640
    depth = _periodic(n, 1) * 3.0 + 1.0
    rgb = np.stack([_periodic(n, s) for s in (2, 3, 4)], axis=-1)
    guide = (rgb * 255).astype(np.float32)
    albedo = Image.fromarray((rgb * 255).astype(np.uint8))
    out = {}

    height_cases = {
        "default": HeightMapOptions(),
        "plane": HeightMapOptions(detrend_mode=DETREND_PLANE),
        "highpass": HeightMapOptions(detrend_mode=DETREND_HIGHPASS, detrend_radius_pct=12.0),
        "none_blur": HeightMapOptions(detrend_mode=DETREND_NONE, blur_radius=6, gamma=1.4),
        "local_eq": HeightMapOptions(local_equalization=0.7),
        "crevice_pos": HeightMapOptions(crevice_suppression=1.5),
        "crevice_neg": HeightMapOptions(crevice_suppression=-1.5),
        "guidance": HeightMapOptions(albedo_guidance=0.6),
        "all": HeightMapOptions(detrend_mode=DETREND_HIGHPASS, blur_radius=3, local_equalization=0.4,
                                crevice_suppression=0.8, albedo_guidance=0.4, invert=True),
    }
    for name, opts in height_cases.items():
        out[f"height_{name}"] = build_height_map(depth, opts, guide=guide)
    guide_small = (np.stack([_periodic(300, s) for s in (5, 6, 7)], -1) * 255).astype(np.float32)
    out["height_guidance_resized"] = build_height_map(depth, HeightMapOptions(albedo_guidance=0.6), guide=guide_small)

    out["preview_downsample"] = downsample_for_preview(_periodic(1500, 9), 1024)
    ext, _box = build_seamless_extended_tile(albedo.resize((500, 500)))
    ehm = build_height_map(np.asarray(ext.convert("L"), np.float32), HeightMapOptions())
    a, b, c = apply_seamless_linear_mask(ehm, orig_size=(500, 500), padding_pct=0.10)
    out["seam_mask_ehm"], out["seam_mask_raw1"], out["seam_mask_map"] = a, b, c
    a2, b2, c2 = apply_seamless_linear_mask(ehm[:-3, :-5], orig_size=(500, 500), padding_pct=0.10)
    out["seam_mask_resized_raw1"] = b2
    out["corner_heal"] = apply_seamless_corner_heal(out["height_default"])
    ext_img, box = build_seamless_extended_tile(albedo.resize((400, 300)))
    out["force_blur"] = np.asarray(apply_force_seamless_blur(ext_img, box), np.float32)

    h = out["height_default"]
    normal_cases = {
        "plain": NormalMapOptions(),
        "preblur": NormalMapOptions(pre_blur_radius=5, strength=2.0),
        "multi": NormalMapOptions(multi_frequency=True, macro_strength=1.6, medium_strength=0.4, micro_strength=2.2),
        "albedo": NormalMapOptions(inject_albedo=True, albedo_strength=0.8, albedo_source=albedo),
        "albedo_resized": NormalMapOptions(inject_albedo=True, albedo_source=albedo.resize((333, 333))),
        "not_seamless": NormalMapOptions(seamless=False, pre_blur_radius=2, invert_y=True),
    }
    for name, opts in normal_cases.items():
        out[f"normal_{name}"] = generate_normal_map(h, opts)

    nrm = out["normal_plain"]
    mask = _periodic(256, 11)
    rough_cases = {
        "plain": RoughnessMapOptions(),
        "window": RoughnessMapOptions(window_pct=5.0, strength=1.7),
        "hybrid": RoughnessMapOptions(height_cavity_factor=0.6, albedo_contrast_factor=0.5,
                                      height_source=h[:500, :500], albedo_source=albedo),
        "mask": RoughnessMapOptions(imperfection_mask=mask, imperfection_strength=0.8, invert=True),
    }
    for name, opts in rough_cases.items():
        out[f"rough_{name}"] = generate_roughness_map(nrm, opts)

    for name, opts in {
        "ray": AOMapOptions(),
        "ray_blur": AOMapOptions(blur_radius=4),
        "classic": AOMapOptions(method="classic", radius=20, blur_radius=2),
    }.items():
        out[f"ao_{name}"] = generate_ao_map(h, opts)

    out["curvature"] = generate_curvature_map(h)

    from ui.imperfection_painter import resize_mask
    out["painter_mask_resize"] = resize_mask(mask, 640, 480)
    return out


def main() -> int:
    mode, path = sys.argv[1], sys.argv[2]
    t = time.time()
    results = scenarios()
    elapsed = time.time() - t
    if mode == "save":
        np.savez_compressed(path, **{k: np.asarray(v) for k, v in results.items()})
        print(f"saved {len(results)} outputs in {elapsed:.1f}s")
        return 0
    base = np.load(path)
    worst = 0.0
    bad = []
    for key, value in results.items():
        ref = base[key]
        value = np.asarray(value)
        if value.shape != ref.shape:
            bad.append(f"{key}: shape {value.shape} vs {ref.shape}")
            continue
        diff = np.abs(value.astype(np.float64) - ref.astype(np.float64))
        scale = max(1.0, float(np.abs(ref).max()))
        rel = float(diff.max()) / scale
        worst = max(worst, rel)
        print(f"  {key:26} max diff {diff.max():.2e}  mean {diff.mean():.2e}  (relative {rel:.2e})")
        if rel > 1e-3:
            bad.append(f"{key}: relative max diff {rel:.2e}")
    print(f"\n{len(results)} outputs in {elapsed:.1f}s, worst relative diff {worst:.2e}")
    if bad:
        print("DIFFERENCES:\n  " + "\n  ".join(bad))
        return 1
    print("All maps match the baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
