"""Build the downloadable AI runtime pack for a release.

The standalone app is built without PyTorch / transformers / diffusers (see
pbrcelain.spec). This script zips those libraries and everything they depend
on, straight from the current Python environment, and writes ai_runtime.json
with the download URL and checksum. pbrcelain.spec bundles that manifest so
the app knows which pack to fetch on first use.

    python build_ai_runtime.py 0.66.0
    PBRCELAIN_VERSION=0.66.0 python -m PyInstaller --noconfirm pbrcelain.spec

Both must be built with the same Python as the app (same version and
architecture), because the pack contains compiled extension modules.
Upload the zip to the GitHub release tagged V<version> (or $PBRCELAIN_RELEASE_TAG).
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import os
import platform
import sys
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement

REPO = "AyberkA0/pbrcelain"
ROOTS = ["torch", "torchvision", "transformers", "diffusers", "accelerate", "huggingface_hub"]
# Shipped inside the app itself; the pack must not shadow them.
IN_APP = {"numpy", "pillow", "pyqt6", "pyqt6-qt6", "pyqt6-sip", "pyopengl"}
# Parts of the libraries the app never touches at runtime.
SKIP_PARTS = ("/include/", "/share/cmake/", "/__pycache__/")

def _key(name: str) -> str:
    return name.lower().replace("_", "-")


def closure() -> list[md.Distribution]:
    env = default_environment()
    env["extra"] = ""
    seen: dict[str, md.Distribution] = {}
    stack = list(ROOTS)
    while stack:
        name = stack.pop()
        key = _key(name)
        if key in seen or key in IN_APP:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[key] = dist
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker is None or req.marker.evaluate(env):
                stack.append(req.name)
    return sorted(seen.values(), key=lambda d: _key(d.metadata["Name"]))


def build(version: str) -> None:
    arch = platform.machine().lower()
    plat = {"darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)
    py = f"py{sys.version_info.major}{sys.version_info.minor}"
    name = f"PBRCELAIN-ai-runtime-{plat}-{arch}-{py}-v{version}.zip"
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
    os.makedirs(out_dir, exist_ok=True)
    archive = os.path.join(out_dir, name)

    tag = os.environ.get("PBRCELAIN_RELEASE_TAG") or f"V{version}"
    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dist in closure():
            for rel in dist.files or []:
                posix = "/" + str(rel).replace(os.sep, "/")
                if str(rel).startswith("..") or any(part in posix for part in SKIP_PARTS) or posix.endswith(".pyc"):
                    continue
                src = dist.locate_file(rel)
                if not os.path.isfile(src):
                    continue
                zf.write(src, str(rel))
                count += 1

    digest = hashlib.sha256()
    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    manifest = {
        "version": version,
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{name}",
        "sha256": digest.hexdigest(),
        "size": os.path.getsize(archive),
        "python": sys.version.split()[0],
    }
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_runtime.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"{count} files -> {archive} ({manifest['size'] / 1e6:.1f} MB)")
    print(f"manifest -> {manifest_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python build_ai_runtime.py <version>")
    build(sys.argv[1])
