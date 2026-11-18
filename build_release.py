"""Build the release files for this platform into release/.

    python build_release.py

macOS (Apple Silicon): PBRCELAIN-<version>-macOS-AppleSilicon.dmg
Windows (x64):         PBRCELAIN-<version>-Windows-x64.zip
both:                  the AI runtime pack PBRCELAIN-ai-runtime-…-v<version>.zip

The version comes from core/version.py. Run it with the Python environment
the app is built from (it needs PyInstaller and the AI libraries; on Windows
the CPU build of PyTorch). See docs/RELEASING.md for the whole release.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "release")
sys.path.insert(0, ROOT)

from core.version import VERSION  # noqa: E402


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def build_macos() -> str:
    from build_macos_app import _build_icns

    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    _build_icns(os.path.join(ROOT, "build", "PBRCELAIN.icns"))
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "pbrcelain.spec")
    staging = os.path.join(ROOT, "build", "dmg")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    run("ditto", os.path.join("dist", "PBRCELAIN.app"), os.path.join(staging, "PBRCELAIN.app"))
    os.symlink("/Applications", os.path.join(staging, "Applications"))
    dmg = os.path.join(OUT, f"PBRCELAIN-{VERSION}-macOS-AppleSilicon.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    run("hdiutil", "create", "-volname", "PBRCELAIN", "-srcfolder", staging, "-format", "ULMO", dmg)
    shutil.rmtree(staging, ignore_errors=True)
    return dmg


def build_windows() -> str:
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "pbrcelain.spec")
    archive = os.path.join(OUT, f"PBRCELAIN-{VERSION}-Windows-x64.zip")
    source = os.path.join(ROOT, "dist", "PBRCELAIN")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for folder, _dirs, files in os.walk(source):
            for name in files:
                path = os.path.join(folder, name)
                zf.write(path, os.path.join("PBRCELAIN", os.path.relpath(path, source)))
    return archive


def main() -> None:
    if sys.platform not in ("darwin", "win32"):
        sys.exit("Release builds are made on macOS or Windows.")
    os.makedirs(OUT, exist_ok=True)
    run(sys.executable, "build_ai_runtime.py")
    packs = glob.glob(os.path.join(ROOT, "build", f"PBRCELAIN-ai-runtime-*-v{VERSION}.zip"))
    for pack in packs:
        shutil.copy2(pack, OUT)
    app = build_macos() if sys.platform == "darwin" else build_windows()
    print(f"\nPBRCELAIN {VERSION}:")
    for path in [app] + [os.path.join(OUT, os.path.basename(p)) for p in packs]:
        print(f"  {path} ({os.path.getsize(path) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
