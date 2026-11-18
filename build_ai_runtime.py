"""Build the downloadable AI runtime pack for a release.

The standalone app is built without PyTorch / transformers / diffusers (see
pbrcelain.spec). This script zips those libraries and everything they depend
on, straight from the current Python environment, and writes ai_runtime.json
with the download URL and checksum. pbrcelain.spec bundles that manifest so
the app knows which pack to fetch on first use.

    python build_ai_runtime.py
    python -m PyInstaller --noconfirm pbrcelain.spec

Both must be built with the same Python as the app (same version and
architecture), because the pack contains compiled extension modules.
The version comes from core/version.py. Upload the zip to the GitHub release
tagged v<version>.

On Windows, PyTorch is left out of the pack. The manifest instead lists the
official PyTorch wheels (URL, SHA-256 and size from download.pytorch.org) in
two variants: the CPU build and the NVIDIA CUDA build. The app downloads the
one the user picks next to the pack. The CUDA wheel is far bigger than a
GitHub release file may be, so it is never re-hosted. The PyTorch version comes
from the current environment; $PBRCELAIN_TORCH_CUDA can pin the CUDA build
(e.g. cu132), otherwise the oldest CUDA version of that release is used.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import os
import platform
import re
import sys
import urllib.parse
import urllib.request
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement

REPO = "AyberkA0/pbrcelain"
ROOTS = ["torch", "torchvision", "transformers", "diffusers", "accelerate", "huggingface_hub"]
# Shipped inside the app itself; the pack must not shadow them.
IN_APP = {"numpy", "pillow", "pyqt6", "pyqt6-qt6", "pyqt6-sip", "pyopengl"}
# Parts of the libraries the app never touches at runtime.
SKIP_PARTS = ("/include/", "/share/cmake/", "/__pycache__/")

TORCH_INDEX = "https://download.pytorch.org/whl"
TORCH_PACKAGES = ("torch", "torchvision")


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


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _index(package: str) -> dict[str, tuple[str, str]]:
    """Wheel file name -> (URL, SHA-256) for every build of `package` on the
    PyTorch index."""
    index = f"{TORCH_INDEX}/{package}/"
    request = urllib.request.Request(index, headers={"User-Agent": "PBRCELAIN-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        html = response.read().decode("utf-8", "replace")
    wheels = {}
    for href in re.findall(r'href="([^"]+)"', html):
        link, _, fragment = href.partition("#")
        sha = fragment.removeprefix("sha256=")
        if re.fullmatch(r"[0-9a-f]{64}", sha):
            wheels[urllib.parse.unquote(link.rsplit("/", 1)[-1])] = (urllib.parse.urljoin(index, link), sha)
    return wheels


def _size(url: str) -> int:
    head = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "PBRCELAIN-build"})
    with urllib.request.urlopen(head, timeout=60) as response:
        return int(response.headers["Content-Length"])


def torch_variants() -> dict:
    """The CPU and CUDA wheels of the installed PyTorch version. Unless
    $PBRCELAIN_TORCH_CUDA names one, the CUDA build is the oldest CUDA version
    that release is published for, as it runs on the widest range of drivers."""
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    versions = {pkg: md.version(pkg).split("+")[0] for pkg in TORCH_PACKAGES}
    indexes = {pkg: _index(pkg) for pkg in TORCH_PACKAGES}

    def wheel_for(pkg: str, build: str) -> str | None:
        """torch must match exactly; the others match on major.minor (their
        CPU and CUDA builds do not always get the same patch releases)."""
        pattern = re.compile(re.escape(f"{pkg}-") + r"(\d+(?:\.\d+)*)" + re.escape(f"+{build}-{py}-{py}-win_amd64.whl"))
        installed = versions[pkg]
        minor = ".".join(installed.split(".")[:2])
        best = None
        for name in indexes[pkg]:
            m = pattern.fullmatch(name)
            if not m:
                continue
            version = m.group(1)
            if version != installed and (pkg == "torch" or ".".join(version.split(".")[:2]) != minor):
                continue
            key = tuple(int(part) for part in version.split("."))
            if best is None or key > best[0]:
                best = (key, name)
        return best[1] if best else None

    build_pattern = re.compile(re.escape(f"torch-{versions['torch']}+") + r"(cu\d+)-")
    builds = {m.group(1) for name in indexes["torch"] if (m := build_pattern.match(name))}
    builds = {b for b in builds if all(wheel_for(pkg, b) for pkg in TORCH_PACKAGES)}
    cuda = os.environ.get("PBRCELAIN_TORCH_CUDA") or min(builds or {""}, key=lambda b: int(b[2:] or 0))
    if not cuda:
        raise SystemExit(f"No CUDA build of torch {versions['torch']} for {py} on Windows.")
    cuda_label = f"CUDA {cuda[2:-1]}.{cuda[-1]}"

    variants = {}
    for name, build, label in (("cpu", "cpu", "CPU"), ("cuda", cuda, f"NVIDIA GPU, {cuda_label}")):
        wheels = []
        for pkg in TORCH_PACKAGES:
            wheel = wheel_for(pkg, build)
            if wheel is None:
                raise SystemExit(f"No {build} wheel of {pkg} {versions[pkg]} for {py} on {TORCH_INDEX}/{pkg}/.")
            url, sha = indexes[pkg][wheel]
            wheels.append({"url": url, "sha256": sha, "size": _size(url)})
        variants[name] = {"label": label, "wheels": wheels}
        print(f"{name}: " + ", ".join(f"{w['url'].rsplit('/', 1)[-1]} ({w['size'] / 1e6:.0f} MB)" for w in wheels))
    return variants


def build(version: str) -> None:
    arch = platform.machine().lower()
    plat = {"darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)
    py = f"py{sys.version_info.major}{sys.version_info.minor}"
    name = f"PBRCELAIN-ai-runtime-{plat}-{arch}-{py}-v{version}.zip"
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
    os.makedirs(out_dir, exist_ok=True)
    archive = os.path.join(out_dir, name)
    separate_torch = sys.platform == "win32"
    variants = torch_variants() if separate_torch else None

    tag = f"v{version}"
    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for dist in closure():
            if separate_torch and _key(dist.metadata["Name"]) in TORCH_PACKAGES:
                continue
            for rel in dist.files or []:
                posix = "/" + str(rel).replace(os.sep, "/")
                if str(rel).startswith("..") or any(part in posix for part in SKIP_PARTS) or posix.endswith(".pyc"):
                    continue
                src = dist.locate_file(rel)
                if not os.path.isfile(src):
                    continue
                zf.write(src, str(rel))
                count += 1

    manifest = {
        "version": version,
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{name}",
        "sha256": _sha256(archive),
        "size": os.path.getsize(archive),
        "python": sys.version.split()[0],
    }
    if variants:
        manifest["torch"] = variants
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_runtime.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"{count} files -> {archive} ({manifest['size'] / 1e6:.1f} MB)")
    print(f"manifest -> {manifest_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit("usage: python build_ai_runtime.py  (the version comes from core/version.py)")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.version import VERSION

    build(VERSION)
