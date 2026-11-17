# Running from source

For contributors and anyone who wants GPU acceleration on Windows. Ready-made builds are on the [Releases page](https://github.com/AyberkA0/pbrcelain/releases).

## Installation

For NVIDIA GPU acceleration:
```bash
python -m venv venv
venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
```

For other:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

On Apple Silicon, the standard `pip install torch torchvision` includes MPS support.

## Running

```bash
venv\Scripts\python main.py
```

Always start the app with the venv's Python so the correct PyTorch build is used.
A project can be opened directly: `venv\Scripts\python main.py my_material.pcln`

### Start menu shortcut and `.pcln` association (Windows)

```bash
venv\Scripts\python register_file_association.py
```

This associates `.pcln` with PBRCELAIN for the current user only
(`HKEY_CURRENT_USER`, no admin rights needed) and adds a PBRCELAIN shortcut to
the Start menu. The app starts without a console window and writes its output to
`%LOCALAPPDATA%\PBRCELAIN\pbrcelain.log`. Re-run the command if you move the
project folder; remove the association and the shortcut with `--unregister`.

### macOS app bundle and `.pcln` association

```bash
venv/bin/python build_macos_app.py
```

This installs a `PBRCELAIN.app` launcher in `~/Applications` that runs this
project folder with the venv's Python. The app shows up under its own name and
icon in the Dock, Launchpad and Spotlight, and double-clicking a `.pcln` file in
Finder (or dropping one on the Dock icon) opens it. Output goes to
`~/Library/Logs/PBRCELAIN/pbrcelain.log`. Re-run the command if you move the
project folder or recreate the venv; remove the app with `--uninstall`
(`--dest DIR` installs elsewhere, e.g. `/Applications`).

### Platform look and input

On macOS and Windows the interface follows the system Light/Dark appearance and
accent color, in each platform's own design language: macOS controls with the
menu bar at the top of the screen, and Windows 11 (Fluent) controls with a
themed title bar and an in-window command bar. Window size and section split are
remembered between sessions, and recent projects are one click away (**File →
Open Recent** on macOS, the arrow next to **Open** on Windows).

Trackpads work in the 3D viewport, tiled preview and imperfection painter:
pinch to zoom and swipe with two fingers to orbit (3D) or pan. The imperfection
painter also takes pen input (Wacom, Surface Pen): pressure sets brush size and
flow, and the pen's eraser end erases. On Windows, long jobs show progress on
the taskbar button.

### App icon

The icon artwork lives in `ui/assets/app_icon_source.jpg`. After replacing it,
run `python make_icons.py` to regenerate the squircle icons (`app_icon.png`,
`app_icon.ico` for Windows, and the macOS version on Apple's icon grid), then
re-run `build_macos_app.py` on macOS.

## Project files (`.pcln`)

Work is saved as a `.pcln` project: a zip archive holding the source images,
generated maps, the raw depth data and every parameter. Reopening a project
restores everything without re-running the depth model. A `.zip` with the same
layout (e.g. a renamed `.pcln`) opens as a project too.

Commands (the File menu on macOS, the command bar on Windows): **New Project /
Open Project / Open Recent / Save / Save As / Export Maps**.
**Export Maps** asks for the Height and Ambient Occlusion bit depth and whether to include a
curvature map, then writes every available map to a folder (PNG, or EXR for
32-bit height maps).
