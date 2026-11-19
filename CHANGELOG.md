# Changelog

PBRCELAIN uses [semantic versioning](https://semver.org): MAJOR.MINOR.PATCH.
The version is set in `core/version.py` and each release is tagged `v<version>`.

## 0.68.1 (2026-11-19)

- Ambient Occlusion no longer disappears from the 3D view after you save its
  adjustments or reopen a project.
- 16-bit and 32-bit (float) images now load correctly: 16-bit TIFFs saved on a
  Mac no longer turn white, float TIFFs no longer turn black, and a 16-bit image
  in the Albedo, Normal or AO slot keeps its tones.
- A new window opens at 1012 x 601.
- macOS: in full screen the title bar icons sit at the left edge.
- The camera pivot fields stay readable with Qt 6.12.
- Windows: uninstalling no longer leaves an empty `.pcln` registry key behind.

## 0.68.0 (2026-11-18)

- Move the camera pivot right in the 3D view: the camera button next to View
  Options shows arrows to drag it along one axis and squares to drag it across
  a plane, as in Unity. The camera holds still while you drag and turns to the
  new pivot when you let go. Double-click the dot in the middle to put the pivot
  back at the origin.
- Windows: a Setup now installs PBRCELAIN (no admin rights needed), adds it to
  the Start menu, opens `.pcln` projects with it, and can remove it again.
- A new project now points at the first step: the Import button while the
  Albedo page is open, otherwise the Albedo slot, with a thin ring instead of
  a glow.
- Taller title bar. On macOS the window buttons are bigger and centred in it,
  and the window no longer shakes while it is dragged. On Windows the title bar
  icons sit at the left edge.
- "More Detail with Chunks" is now called **Full Resolution with Chunk Estimation**.

## 0.67.0 (2026-11-18)

First public release.

- Turn one photo into Height, Normal, Roughness and Ambient Occlusion maps,
  previewed live on a 3D view, with Depth Anything V2 or Marigold depth models.
- **More Detail with Chunks** keeps the photo's full resolution (4K, 8K and up)
  and **seamless** generation makes every map tileable.
- Windows: NVIDIA GPU (CUDA) support. On first use the app offers the GPU
  version of the AI components when an NVIDIA card is found, or the CPU version.
- Windows: frameless window with the same layout, fonts and controls as on macOS,
  and Windows caption buttons.
- Undo and redo for every setting (camera moves are not part of undo).
- Command line for scripts and AI agents (`pbrcelain generate`, `settings`,
  `models`, `version`), answering in JSON.
- Projects are saved as `.pcln` files that keep every map and setting.
