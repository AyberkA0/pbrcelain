"""On-demand AI runtime for the packaged app.

The standalone app ships without PyTorch, transformers and diffusers so the
download stays small. The first time a depth model is needed, the matching AI
runtime pack (built alongside the app, see build_ai_runtime.py) is downloaded
from the GitHub release, checked against its SHA-256, unpacked into the user's
application-support folder and put on sys.path.

On Windows the pack holds everything but PyTorch itself. The manifest lists the
official PyTorch wheels in two variants, CPU and NVIDIA GPU (CUDA), and the
chosen one is downloaded from download.pytorch.org and unpacked next to the
pack. The user can switch variants later; the new one replaces the old.

When running from source (not frozen) nothing is downloaded: the libraries
come from the normal Python environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

MANIFEST_NAME = "ai_runtime.json"
_MARKER = ".complete"
_CURRENT = "current.json"
_PROBE = "torch"
_RETRIES = 4
# Unpacked size is about this many times the download (compressed wheels).
_UNPACK_FACTOR = 1.8

ProgressCB = Optional[Callable[[int, int, str], None]]


@dataclass
class Download:
    url: str
    sha256: str
    size: int


@dataclass
class Variant:
    name: str
    label: str
    wheels: list[Download]

    @property
    def size(self) -> int:
        return sum(w.size for w in self.wheels)


@dataclass
class Manifest:
    url: str
    sha256: str
    size: int
    version: str
    variants: dict[str, Variant] = field(default_factory=dict)


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
    variants = {
        name: Variant(name, spec["label"], [Download(w["url"], w["sha256"], int(w["size"])) for w in spec["wheels"]])
        for name, spec in (data.get("torch") or {}).items()
    }
    return Manifest(url=url, sha256=data["sha256"], size=int(data["size"]), version=data["version"], variants=variants)


# -- variants ----------------------------------------------------------------

def variants() -> dict[str, Variant]:
    """PyTorch builds the user can choose from (empty when the pack holds PyTorch)."""
    manifest = load_manifest()
    return manifest.variants if manifest else {}


_gpu_name_cache: list = []


def nvidia_gpu() -> Optional[str]:
    """Name of the NVIDIA graphics card, or None when there is no NVIDIA driver."""
    if _gpu_name_cache:
        return _gpu_name_cache[0]
    name = None
    if sys.platform == "win32":
        system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        if os.path.isfile(os.path.join(system, "nvcuda.dll")):
            name = "NVIDIA GPU"
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                first = out.stdout.strip().splitlines()[0].strip() if out.returncode == 0 and out.stdout.strip() else ""
                name = first or name
            except (OSError, subprocess.SubprocessError):
                pass
    _gpu_name_cache.append(name)
    return name


def default_variant() -> Optional[str]:
    """The variant to offer first: the GPU build when an NVIDIA card is present.
    $PBRCELAIN_AI_VARIANT (cpu or cuda) overrides it."""
    options = variants()
    if not options:
        return None
    wanted = os.environ.get("PBRCELAIN_AI_VARIANT", "").strip().lower()
    if wanted in options:
        return wanted
    return "cuda" if "cuda" in options and nvidia_gpu() else "cpu"


# -- installed state ---------------------------------------------------------

def install_dir(manifest: Manifest, variant: Optional[str] = None) -> str:
    name = manifest.sha256[:16] + (f"-{variant}" if variant else "")
    return os.path.join(_base_dir(), name)


def _read_current() -> dict:
    try:
        with open(os.path.join(_base_dir(), _CURRENT), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _installed_dir(manifest: Manifest) -> Optional[str]:
    """The installed runtime for this manifest: the one chosen last, else any."""
    current = _read_current().get("dir")
    names = [current] if current else []
    names += [os.path.basename(install_dir(manifest, v)) for v in ("cuda", "cpu")] if manifest.variants else []
    names.append(os.path.basename(install_dir(manifest)))
    prefix = manifest.sha256[:16]
    for name in names:
        if not name or not name.startswith(prefix):
            continue
        path = os.path.join(_base_dir(), name)
        if os.path.isfile(os.path.join(path, _MARKER)):
            return path
    return None


def installed_variant() -> Optional[str]:
    """'cpu' or 'cuda' for the installed runtime, None when unknown or not installed."""
    manifest = load_manifest()
    path = _installed_dir(manifest) if manifest else None
    if not path:
        return None
    suffix = os.path.basename(path)[16:].lstrip("-")
    return suffix or None


def _importable() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(_PROBE) is not None
    except (ImportError, ValueError):
        return False


def _use(path: str) -> None:
    """Put `path` on sys.path in place of any other runtime folder. Child
    processes (the depth model) inherit sys.path, so they get the same one."""
    base = os.path.normcase(os.path.abspath(_base_dir()))
    sys.path[:] = [p for p in sys.path if not os.path.normcase(os.path.abspath(p or ".")).startswith(base)]
    sys.path.insert(0, path)
    import importlib

    importlib.invalidate_caches()


def activate() -> bool:
    """Make the AI libraries importable. Returns True when they are."""
    if _importable():
        return True
    manifest = load_manifest()
    if manifest is None:
        return False
    target = _installed_dir(manifest)
    if target is None:
        return False
    _use(target)
    return _importable()


def needs_download() -> bool:
    return is_frozen() and not activate() and load_manifest() is not None


def download_size(variant: Optional[str] = None) -> int:
    manifest = load_manifest()
    if manifest is None:
        return 0
    variant = variant or default_variant()
    extra = manifest.variants[variant].size if variant in manifest.variants else 0
    return manifest.size + extra


# -- download ----------------------------------------------------------------

def _fetch(item: Download, dest: str, label: str, offset: int, total: int,
           progress: ProgressCB, cancelled: Callable[[], bool]) -> None:
    """Download `item` to `dest`, resuming after dropped connections, and check
    its SHA-256. Progress counts from `offset` within `total`."""
    attempt = 0
    while True:
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        headers = {"User-Agent": "PBRCELAIN"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            request = urllib.request.Request(item.url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                if have and response.status != 206:
                    have = 0  # the server ignored the range: start over
                with open(dest, "ab" if have else "wb") as out:
                    done = have
                    while True:
                        if cancelled():
                            raise InterruptedError("Download cancelled.")
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(offset + done, total, label)
            if os.path.getsize(dest) >= item.size:
                break
            raise ConnectionError("The connection closed early.")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f"Download failed: {exc}") from exc
            attempt += 1
            if attempt > _RETRIES:
                raise RuntimeError(f"Download failed after {_RETRIES} retries: {exc}") from exc
            if progress:
                progress(offset + have, total, "Connection lost, retrying…")
            time.sleep(min(2 ** attempt, 15))

    digest = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != item.sha256:
        os.remove(dest)
        raise RuntimeError("The downloaded AI components are damaged (checksum mismatch). Please try again.")


def _remove_others(keep: str) -> None:
    """Delete other installed runtimes (older versions, the other variant). A
    folder still in use by a running process may stay behind; without its
    marker it is never picked again and goes on the next install."""
    base = _base_dir()
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if path == keep or not os.path.isdir(path):
            continue
        try:
            os.remove(os.path.join(path, _MARKER))
        except OSError:
            pass
        shutil.rmtree(path, ignore_errors=True)


def install(progress: ProgressCB = None, cancelled: Callable[[], bool] = lambda: False,
            variant: Optional[str] = None) -> None:
    """Download, verify and unpack the AI runtime. Raises on failure."""
    manifest = load_manifest()
    if manifest is None:
        raise RuntimeError("This build has no AI runtime manifest.")
    if manifest.variants:
        variant = variant or default_variant()
        if variant not in manifest.variants:
            raise RuntimeError(f"Unknown AI components variant: {variant}")
        items = [(Download(manifest.url, manifest.sha256, manifest.size), "Downloading AI components…")]
        label = manifest.variants[variant].label
        items += [(w, f"Downloading PyTorch ({label})…") for w in manifest.variants[variant].wheels]
    else:
        variant = None
        items = [(Download(manifest.url, manifest.sha256, manifest.size), "Downloading AI components…")]
    total = sum(item.size for item, _ in items)

    target = install_dir(manifest, variant)
    base = _base_dir()
    os.makedirs(base, exist_ok=True)
    free = shutil.disk_usage(base).free
    needed = int(total * (1 + _UNPACK_FACTOR))
    if free < needed:
        raise RuntimeError(
            f"Not enough free disk space for the AI components: {needed / 1e9:.1f} GB needed, "
            f"{free / 1e9:.1f} GB free on the drive with {base}."
        )

    staging = target + ".partial"
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    archive = None
    try:
        offset = 0
        for item, label in items:
            fd, archive = tempfile.mkstemp(prefix="ai-download-", suffix=".zip", dir=base)
            os.close(fd)
            os.remove(archive)
            _fetch(item, archive, label, offset, total, progress, cancelled)
            offset += item.size
            if progress:
                progress(0, 0, "Unpacking AI components…")
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)
            os.remove(archive)
            archive = None
        _restore_permissions(staging)
        if os.path.isdir(target):
            shutil.rmtree(target)
        os.replace(staging, target)
        with open(os.path.join(target, _MARKER), "w", encoding="utf-8") as f:
            f.write(manifest.version)
        with open(os.path.join(base, _CURRENT), "w", encoding="utf-8") as f:
            json.dump({"dir": os.path.basename(target), "variant": variant}, f)
    finally:
        if archive and os.path.exists(archive):
            os.remove(archive)
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)

    _remove_others(target)
    _use(target)
    if not _importable():
        raise RuntimeError("The AI components were installed but could not be loaded.")


def _restore_permissions(root: str) -> None:
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith((".dylib", ".so")) or "/bin/" in os.path.join(folder, name):
                path = os.path.join(folder, name)
                os.chmod(path, os.stat(path).st_mode | 0o755)
