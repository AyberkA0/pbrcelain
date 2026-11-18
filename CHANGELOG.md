# Changelog

PBRCELAIN uses [semantic versioning](https://semver.org): MAJOR.MINOR.PATCH.
The version is set in `core/version.py` and each release is tagged `v<version>`.

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
