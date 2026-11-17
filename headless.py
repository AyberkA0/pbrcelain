"""Command-line interface: generate PBR maps without opening the window.

Made for scripts and LLM agents. Every command prints exactly one JSON object
on stdout (progress and logs go to stderr) and exits with 0 on success, 1 on
failure, so a caller can always parse the result.

    pbrcelain generate photo.jpg --out maps/
    pbrcelain generate photo.jpg --out maps/ --maps normal,roughness --height height.png
    pbrcelain settings > settings.json        # every option, with app defaults
    pbrcelain generate photo.jpg --out maps/ --settings settings.json
    pbrcelain models

Settings use the same keys and defaults as the app (they are read from the
app's own panels), so a result matches what the window would produce. A .pcln
project can be passed to --settings to reuse its settings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

COMMANDS = ("generate", "settings", "models")
MAP_NAMES = ("height", "normal", "roughness", "ao", "curvature")
DEVICES = ("auto", "cpu", "mps", "cuda")


def is_cli_invocation(argv: list[str]) -> bool:
    return len(argv) > 1 and argv[1] in COMMANDS + ("--help", "-h", "help")


# -- output -----------------------------------------------------------------

def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _emit(payload: dict) -> None:
    out = sys.__stdout__ or sys.stdout
    out.write(json.dumps(payload, indent=2) + "\n")
    out.flush()


class CliError(Exception):
    pass


# -- panels (the source of defaults and settings) ------------------------------

def _panels():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import qInstallMessageHandler
    from PyQt6.QtWidgets import QApplication

    # The hidden panels only supply settings; Qt's notes about the offscreen
    # platform (fonts, size hints) are noise for a caller reading stderr.
    qInstallMessageHandler(lambda *_args: None)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from ui.panels.albedo_panel import AlbedoPanel
    from ui.panels.ao_panel import AOPanel
    from ui.panels.height_panel import HeightPanel
    from ui.panels.normal_panel import NormalPanel
    from ui.panels.roughness_panel import RoughnessPanel

    panels = {
        "albedo": AlbedoPanel(),
        "height": HeightPanel(),
        "normal": NormalPanel(),
        "roughness": RoughnessPanel(),
        "ao": AOPanel(),
    }
    return app, panels


def _load_settings(path: str) -> dict:
    if not os.path.isfile(path):
        raise CliError(f"Settings file not found: {path}")
    from core.project import is_project_path

    if is_project_path(path):
        import zipfile

        try:
            with zipfile.ZipFile(path) as zf:
                payload = json.loads(zf.read("project.json").decode("utf-8"))
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise CliError(f"Not a PBRCELAIN project: {path}") from None
        slots = payload.get("map_slots", {})
        return {name: slot.get("options", {}) for name, slot in slots.items() if name in ("albedo", "height", "normal", "roughness", "ao")}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise CliError(f"Settings file is not valid JSON: {exc}") from None
    if isinstance(data, dict) and isinstance(data.get("settings"), dict):
        data = data["settings"]  # the output of `pbrcelain settings`, passed as is
    if not isinstance(data, dict):
        raise CliError("Settings JSON must be an object keyed by map name (albedo, height, normal, roughness, ao).")
    unknown = set(data) - {"albedo", "height", "normal", "roughness", "ao"}
    if unknown:
        raise CliError(f"Unknown map name(s) in settings: {', '.join(sorted(unknown))}")
    return data


# -- commands -------------------------------------------------------------------

def cmd_settings(_args) -> dict:
    _app, panels = _panels()
    return {"ok": True, "settings": {name: panel.to_options_dict() for name, panel in panels.items()}}


def cmd_models(_args) -> dict:
    from core.depth_models import MODEL_CATALOG

    licenses = {
        "depth-anything/Depth-Anything-V2-Small-hf": "Apache-2.0",
        "depth-anything/Depth-Anything-V2-Base-hf": "CC-BY-NC-4.0 (non-commercial)",
        "depth-anything/Depth-Anything-V2-Large-hf": "CC-BY-NC-4.0 (non-commercial)",
        "prs-eth/marigold-depth-lcm-v1-0": "Apache-2.0",
        "prs-eth/marigold-depth-v1-1": "CreativeML-OpenRAIL++-M",
    }
    models = [
        {"model": family, "size": variant, "checkpoint": checkpoint, "license": licenses.get(checkpoint, "see model card")}
        for family, variants in MODEL_CATALOG.items()
        for variant, checkpoint in variants.items()
    ]
    return {"ok": True, "models": models, "devices": list(DEVICES), "default": {"model": "Depth Anything V2", "size": "Small", "device": "auto"}}


def _ensure_ai_runtime() -> None:
    from core import ai_runtime

    if ai_runtime.needs_download():
        size = ai_runtime.download_size() / 1e6
        _log(f"Downloading AI components ({size:.0f} MB, once)…")
        last = [0.0]

        def progress(done, total, text):
            if total and time.time() - last[0] > 2:
                last[0] = time.time()
                _log(f"{text} {done / total * 100:.0f}%")

        ai_runtime.install(progress=progress)
    ai_runtime.activate()


def _estimate_depth(albedo, panels, args):
    from core.depth_models import DepthEstimator
    from core.height_map import apply_force_seamless_blur, build_seamless_extended_tile

    height_panel = panels["height"]
    family, variant = height_panel.selected_family_variant()
    family = args.model or family
    variant = args.size or variant
    device = args.device or height_panel.selected_device()
    seamless = height_panel.is_seamless_generation() if args.seamless is None else args.seamless
    chunked = height_panel.is_chunked() if args.chunks is None else args.chunks

    source, seamless_size = albedo, None
    if seamless:
        source, tile_box = build_seamless_extended_tile(albedo, padding_pct=0.10)
        if height_panel.is_force_seamless_blur():
            source = apply_force_seamless_blur(source, tile_box, blur_pct=0.03)
        seamless_size = albedo.size

    _ensure_ai_runtime()
    try:
        estimator = DepthEstimator(family, variant, device)
    except ValueError as exc:
        raise CliError(f"{exc}. Run `pbrcelain models` for the valid names.") from None
    estimator.load(progress_cb=lambda m: _log(m.splitlines()[0]))
    if chunked:
        tile_size, overlap_pct, batch_size = height_panel.chunk_params()
        result = estimator.infer_tiled(
            source, tile_size=tile_size, overlap_pct=overlap_pct, batch_size=batch_size, progress_cb=_log
        )
    else:
        result = estimator.infer(source, progress_cb=_log)
    result.seamless_orig_size = seamless_size
    estimator.unload()
    return result, {"model": family, "size": variant, "device": estimator.device, "seamless": seamless, "chunks": chunked}


def cmd_generate(args) -> dict:
    started = time.time()
    if not os.path.isfile(args.albedo):
        raise CliError(f"Albedo image not found: {args.albedo}")
    wanted = [m.strip() for m in args.maps.split(",") if m.strip()]
    bad = [m for m in wanted if m not in MAP_NAMES]
    if bad:
        raise CliError(f"Unknown map(s): {', '.join(bad)}. Choose from: {', '.join(MAP_NAMES)}")
    if args.model is not None or args.size is not None:
        from core.depth_models import LEGACY_VARIANTS, MODEL_CATALOG

        if args.size is not None:
            args.size = LEGACY_VARIANTS.get(args.size, args.size)
        family = args.model or "Depth Anything V2"
        if family not in MODEL_CATALOG or (args.size and args.size not in MODEL_CATALOG[family]):
            raise CliError("Unknown model/size. Run `pbrcelain models` for the valid names.")

    import numpy as np
    from PIL import Image

    from core.albedo_adjust import apply_albedo_adjustments
    from core.ao_map import generate_ao_map
    from core.ao_map import to_image as ao_to_image
    from core.curvature_map import generate_curvature_map
    from core.curvature_map import to_image as curvature_to_image
    from core.height_map import apply_seamless_linear_mask, build_height_map, safe_save_image
    from core.height_map import to_image as height_to_image
    from core.normal_map import generate_normal_map
    from core.normal_map import to_image as normal_to_image
    from core.roughness_map import generate_roughness_map
    from core.roughness_map import to_image as roughness_to_image

    _app, panels = _panels()
    if args.settings:
        for name, data in _load_settings(args.settings).items():
            panels[name].apply_options_dict(data)

    try:
        albedo_src = Image.open(args.albedo)
        albedo_src.load()
        albedo_src = albedo_src.convert("RGB")
    except Exception as exc:
        raise CliError(f"Could not read the albedo image: {exc}") from None

    os.makedirs(args.out, exist_ok=True)
    outputs: dict[str, str] = {}
    info: dict = {"resolution": list(albedo_src.size)}

    def save(name: str, image) -> None:
        path = safe_save_image(image, os.path.join(args.out, f"{name}.png"))
        outputs[name] = os.path.abspath(path)
        _log(f"Wrote {path}")

    # Albedo: written only when an adjustment is switched on in the settings.
    albedo_panel = panels["albedo"]
    adjust = albedo_panel.current_adjust_options()
    rules = albedo_panel.current_shift_rules()
    albedo = albedo_src
    if adjust.white_balance_enabled or adjust.seamless_enabled or any(r.enabled for r in rules):
        albedo = apply_albedo_adjustments(albedo_src, options=adjust, rules=rules)
        save("albedo", albedo)

    needs_height = any(m in wanted for m in ("height", "normal", "roughness", "ao", "curvature"))
    height_arr: Optional[np.ndarray] = None
    if needs_height:
        if args.height:
            try:
                img = Image.open(args.height)
                img.load()
            except Exception as exc:
                raise CliError(f"Could not read the height image: {exc}") from None
            if img.mode in ("I;16", "I"):
                height_arr = np.asarray(img, dtype=np.float32) / 65535.0
            elif img.mode == "F":
                height_arr = np.asarray(img, dtype=np.float32).clip(0.0, 1.0)
            else:
                height_arr = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
            info["height_source"] = os.path.abspath(args.height)
        else:
            result, model_info = _estimate_depth(albedo, panels, args)
            info.update(model_info)
            options = panels["height"].current_options()
            height_arr = build_height_map(result.depth, options, guide=result.guide)
            if result.seamless_orig_size is not None:
                _, height_arr, _ = apply_seamless_linear_mask(height_arr, orig_size=result.seamless_orig_size, padding_pct=0.10)
        if "height" in wanted and not args.height:
            save("height", height_to_image(height_arr, bit_depth=args.height_bits))

    normal_arr = None
    if "normal" in wanted or "roughness" in wanted:
        from dataclasses import replace

        normal_options = replace(panels["normal"].current_options(), seamless=True)
        normal_options.albedo_source = albedo
        normal_arr = generate_normal_map(height_arr, normal_options)
        normal_img = normal_to_image(normal_arr)
        if "normal" in wanted:
            save("normal", normal_img)
        # The app builds roughness from the saved 8-bit normal map; do the same.
        normal_arr = np.asarray(normal_img.convert("RGB"), dtype=np.float32) / 255.0

    if "roughness" in wanted:
        roughness_options = panels["roughness"].current_options()
        roughness_options.height_source = height_arr
        roughness_options.albedo_source = albedo
        save("roughness", roughness_to_image(generate_roughness_map(normal_arr, roughness_options)))

    if "ao" in wanted:
        ao_options = panels["ao"].current_options()
        save("ao", ao_to_image(generate_ao_map(height_arr, ao_options), bit_depth=args.ao_bits))

    if "curvature" in wanted:
        save("curvature", curvature_to_image(generate_curvature_map(height_arr)))

    info["seconds"] = round(time.time() - started, 2)
    return {"ok": True, "outputs": outputs, **info}


# -- entry ----------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    """Usage errors become a JSON answer like every other failure."""

    def error(self, message: str):
        raise CliError(f"{message}. Run `pbrcelain {self.prog.split()[-1] if ' ' in self.prog else ''} --help`.".replace("  ", " "))


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pbrcelain",
        description="Generate PBR texture maps (height, normal, roughness, ambient occlusion) from one photo. "
        "Prints one JSON object on stdout; progress goes to stderr.",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    gen = sub.add_parser("generate", help="Generate maps from an albedo (color) photo.")
    gen.add_argument("albedo", help="Path to the albedo / color photo (PNG, JPG, TIFF…).")
    gen.add_argument("--out", "-o", required=True, help="Folder to write the maps into (created if missing).")
    gen.add_argument(
        "--maps", default="height,normal,roughness,ao",
        help=f"Comma-separated maps to write: {', '.join(MAP_NAMES)}. Default: height,normal,roughness,ao.",
    )
    gen.add_argument("--height", help="Use this existing height map instead of running the AI depth model.")
    gen.add_argument("--settings", help="JSON from `pbrcelain settings` (edited), or a .pcln project, to override defaults.")
    gen.add_argument("--model", help="Depth model family, e.g. 'Depth Anything V2' or 'Marigold'. See `pbrcelain models`.")
    gen.add_argument("--size", help="Model size/variant, e.g. Small, Base, Large (Depth Anything) or Fast, Standard (Marigold).")
    gen.add_argument("--device", choices=DEVICES, help="Where the model runs. Default: auto.")
    gen.add_argument("--seamless", dest="seamless", action="store_true", default=None, help="Make the height map tileable.")
    gen.add_argument("--no-seamless", dest="seamless", action="store_false", help="Do not make it tileable.")
    gen.add_argument("--chunks", dest="chunks", action="store_true", default=None, help="Process in chunks for more detail on large images (slower).")
    gen.add_argument("--no-chunks", dest="chunks", action="store_false", help="Single pass (default).")
    gen.add_argument("--height-bits", type=int, choices=(8, 16, 32), default=16, help="Height map bit depth. 32 writes OpenEXR. Default: 16.")
    gen.add_argument("--ao-bits", type=int, choices=(8, 16), default=8, help="Ambient occlusion bit depth. Default: 8.")

    sub.add_parser("settings", help="Print every setting with the app's defaults, as JSON usable with --settings.")
    sub.add_parser("models", help="List depth models, sizes, devices and licenses.")
    return parser


def run(argv: list[str]) -> int:
    parser = _parser()
    if len(argv) <= 1 or argv[1] in ("help",):
        parser.print_help(sys.__stdout__ or sys.stdout)
        return 0
    try:
        args = parser.parse_args(argv[1:])
    except CliError as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1
    handlers = {"generate": cmd_generate, "settings": cmd_settings, "models": cmd_models}
    # Library chatter (print() from model loading) must not pollute the JSON on stdout.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        payload = handlers[args.command](args)
        code = 0
    except CliError as exc:
        payload, code = {"ok": False, "error": str(exc)}, 1
    except Exception as exc:  # unexpected: still answer in JSON
        payload, code = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 1
    finally:
        sys.stdout = real_stdout
    _emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv))
