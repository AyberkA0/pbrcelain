"""On-demand AI runtime for the packaged app.

The standalone app ships without PyTorch, transformers and diffusers so the
download stays small. The first time a depth model is needed, the matching AI
runtime pack (built alongside the app, see build_ai_runtime.py) is downloaded
from the GitHub release, checked against its SHA-256, unpacked into the user's
application-support folder and put on sys.path.

When running from source (not frozen) nothing is downloaded: the libraries
come from the normal Python environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable, Optional

MANIFEST_NAME = "ai_runtime.json"
_MARKER = ".complete"
_PROBE = "torch"

ProgressCB = Optional[Callable[[int, int, str], None]]


@dataclass
class Manifest:
    url: str
    sha256: str
    size: int
    version: str


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _base_dir() -> str:
    if sys.platform == "darwin":
        root = os.path.expanduser("~/Library/Application Support/PBRCELAIN")
    else:
        root = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PBRCELAIN")
    return os.path.join(root, "ai-runtime")


def load_manifest() -> Optional[Manifest]:
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(here, MANIFEST_NAME)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # PBRCELAIN_AI_RUNTIME_URL lets a test build fetch the pack from elsewhere (e.g. file://).
    url = os.environ.get("PBRCELAIN_AI_RUNTIME_URL") or data["url"]
    return Manifest(url=url, sha256=data["sha256"], size=int(data["size"]), version=data["version"])


def install_dir(manifest: Manifest) -> str:
    return os.path.join(_base_dir(), manifest.sha256[:16])


def _importable() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(_PROBE) is not None
    except (ImportError, ValueError):
        return False


def activate() -> bool:
    """Make the AI libraries importable. Returns True when they are."""
    if _importable():
        return True
    manifest = load_manifest()
    if manifest is None:
        return False
    target = install_dir(manifest)
    if not os.path.isfile(os.path.join(target, _MARKER)):
        return False
    if target not in sys.path:
        sys.path.insert(0, target)
    import importlib

    importlib.invalidate_caches()
    return _importable()


def needs_download() -> bool:
    return is_frozen() and not activate() and load_manifest() is not None


def download_size() -> int:
    manifest = load_manifest()
    return manifest.size if manifest else 0


def install(progress: ProgressCB = None, cancelled: Callable[[], bool] = lambda: False) -> None:
    """Download, verify and unpack the AI runtime. Raises on failure."""
    manifest = load_manifest()
    if manifest is None:
        raise RuntimeError("This build has no AI runtime manifest.")
    target = install_dir(manifest)
    os.makedirs(_base_dir(), exist_ok=True)

    fd, archive = tempfile.mkstemp(prefix="ai-runtime-", suffix=".zip", dir=_base_dir())
    os.close(fd)
    staging = target + ".partial"
    try:
        digest = hashlib.sha256()
        request = urllib.request.Request(manifest.url, headers={"User-Agent": "PBRCELAIN"})
        with urllib.request.urlopen(request, timeout=60) as response, open(archive, "wb") as out:
            total = int(response.headers.get("Content-Length") or manifest.size)
            done = 0
            while True:
                if cancelled():
                    raise InterruptedError("Download cancelled.")
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total, "Downloading AI components…")
        if digest.hexdigest() != manifest.sha256:
            raise RuntimeError("The downloaded AI components are damaged (checksum mismatch). Please try again.")

        if progress:
            progress(0, 0, "Unpacking AI components…")
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        _restore_permissions(staging)
        if os.path.isdir(target):
            shutil.rmtree(target)
        os.replace(staging, target)
        with open(os.path.join(target, _MARKER), "w", encoding="utf-8") as f:
            f.write(manifest.version)
    finally:
        if os.path.exists(archive):
            os.remove(archive)
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    if not activate():
        raise RuntimeError("The AI components were installed but could not be loaded.")


def _restore_permissions(root: str) -> None:
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith((".dylib", ".so")) or "/bin/" in os.path.join(folder, name):
                path = os.path.join(folder, name)
                os.chmod(path, os.stat(path).st_mode | 0o755)
