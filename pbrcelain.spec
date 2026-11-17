import os
import sys

import glob
import importlib.util

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

APP_NAME = "PBRCELAIN"
VERSION = os.environ.get("PBRCELAIN_VERSION", "1.0.0")
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# The AI libraries (PyTorch, transformers, diffusers and their dependencies) are
# not bundled: build_ai_runtime.py packs them separately and the app downloads
# that pack on first use (core/ai_runtime.py). They are excluded below.
AI_MODULES = [
    "torch", "torchvision", "functorch", "torchgen", "transformers", "diffusers", "accelerate",
    "huggingface_hub", "hf_xet", "tokenizers", "safetensors", "sympy", "mpmath", "networkx",
    "regex", "timm", "jinja2", "markupsafe", "fsspec", "filelock", "yaml", "tqdm", "psutil",
    "scipy", "pandas",
]

hiddenimports = ["OpenGL.platform.darwin" if IS_MAC else "OpenGL.platform.win32", "PyQt6.QtSvg"]
# The downloaded AI libraries rely on standard-library modules the app itself
# never imports, so the whole standard library is bundled.
_SKIP_STDLIB = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv", "this", "antigravity"}
for _name in sorted(sys.stdlib_module_names):
    if _name in _SKIP_STDLIB or _name.startswith("_"):
        continue
    _spec = importlib.util.find_spec(_name)
    if _spec is None:
        continue
    hiddenimports += collect_submodules(_name, filter=lambda m: ".test" not in m and "idle" not in m) if _spec.submodule_search_locations else [_name]

# Libraries shared by the app and the downloaded AI pack are bundled in full,
# since the AI code uses parts of them the app never imports itself.
for _shared in ("PIL", "numpy"):
    hiddenimports += collect_submodules(_shared, filter=lambda m: ".tests" not in m and ".testing" not in m)

datas = [("ui/assets", "ui/assets")]
if os.path.isfile("ai_runtime.json"):
    datas.append(("ai_runtime.json", "."))
for dist in ("numpy", "pillow", "opencv-python-headless", "PyOpenGL"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

binaries = []

a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(".")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "tensorflow", "jax", "flax",
        *AI_MODULES,
    ],
    noarchive=False,
)
# Qt pieces the app never uses: PDF and network support, translations,
# and image-format / platform plugins other than the ones we need.
_QT_DROP = (
    "QtPdf", "QtNetwork", "Qt6/translations",
    "imageformats/libqpdf", "imageformats/libqgif", "imageformats/libqtiff", "imageformats/libqwebp",
    "imageformats/libqtga", "imageformats/libqwbmp", "imageformats/libqico", "imageformats/libqmacheif",
    "imageformats/libqmacjp2", "platforms/libqminimal", "generic/libqtuiotouch",
)


def _keep(entry) -> bool:
    path = entry[0].replace("\\", "/")
    return not any(part in path for part in _QT_DROP)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

icon = "build/PBRCELAIN.icns" if IS_MAC else "ui/assets/app_icon.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,
    icon=icon,
    upx=False,
    target_arch="arm64" if IS_MAC else None,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.pbrcelain.PBRCELAIN",
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "LSApplicationCategoryType": "public.app-category.graphics-design",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PBRCELAIN Project",
                "CFBundleTypeRole": "Editor",
                "CFBundleTypeIconFile": "PBRCELAIN.icns",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["com.pbrcelain.project"],
            }],
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "com.pbrcelain.project",
                "UTTypeDescription": "PBRCELAIN Project",
                "UTTypeConformsTo": ["public.data", "public.composite-content"],
                "UTTypeIconFile": "PBRCELAIN.icns",
                "UTTypeTagSpecification": {"public.filename-extension": ["pcln"]},
            }],
        },
    )
