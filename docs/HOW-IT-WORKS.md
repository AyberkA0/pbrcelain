# How PBRCELAIN works

A closer look at what happens behind each map. For downloading and getting started, see the [README](../README.md).

## Height map generation

### Depth models

| Family | Variants | Character | License |
| --- | --- | --- | --- |
| **Depth Anything V2** | Small / Base / Large | Fast, stable relative depth; great general-purpose default. | Small: Apache 2.0. Base, Large: CC BY-NC 4.0 (non-commercial) |
| **Marigold** | Fast / Standard | Diffusion-based; exceptional micro-relief on joints, grain and organic surfaces. | Fast: Apache 2.0. Standard: CreativeML Open RAIL++-M |

Models are downloaded from Hugging Face on first use and can run on **CUDA GPUs**,
**Apple Silicon (MPS)** or **CPU**. If a GPU is explicitly selected but not
available, the app reports why (e.g. a CPU-only PyTorch build) instead of
silently falling back to CPU.

### Chunk estimation (high-resolution detail)

A single model pass squeezes the whole photo into the model's native input size
(518 px for Depth Anything, 768 px for Marigold), which smears fine detail on
large images. Chunk estimation instead:

1. runs one full-image pass as a trusted large-scale reference,
2. re-runs the model on overlapping crops near its native resolution,
3. calibrates each crop's scale/offset to the reference (least-squares fit),
4. cross-fades the crops back together.

**Quality** (ultra / high / medium / low) controls the chunk size, **Batch size**
processes several chunks per forward pass on GPUs with enough VRAM, and the
height map refines live on screen while chunks are processed.

### Seamless (tileable) generation

With **Seamless** enabled, the source is expanded into a 3×3 tiled canvas before
inference, so the model sees real neighboring content across every edge. The
result is cropped back and the borders and corners are blended so the height map
tiles with no visible seam. **Force seamless with blur** additionally softens hard
seams in the source photo before the depth model runs.

### Correcting depth-model artifacts

Monocular depth models are trained on perspective scenes, so on flat material
photos they tend to add a large-scale "bowl" or "dome" shape. The Adjustment page
fixes this and shapes the relief — all non-destructively, on the raw depth data:

- **Remove bending** — remove bowl/dome (quadratic fit), remove tilt (plane
  fit), high-pass, or keep raw depth.
- **Correction curve editor** — separate X / Y curves that control how much
  correction is applied at each distance from the center, with live preview.
- **Gaps & cracks**
  - *Level out* levels regional lighting and tilt differences so all
    features sit on the same base plane.
  - *Deepen cracks* pushes mortar lines and joints down and lifts the surfaces
    between them (or softens them with negative values).
  - *Use photo edges* uses edges in the source photo to keep joints at the bottom.
- **Tone & smoothing** — invert, gamma, smoothing, percentile clipping (low/high),
  post-process seamless wrap.
- **Output** — 8-bit PNG, 16-bit PNG or 32-bit float OpenEXR, chosen when exporting.

Edits preview instantly on a downscaled copy; **Save** commits them at full
resolution, **Revert** discards them. The raw depth field is stored in the
project file, so height adjustments stay editable after reopening a project
without re-running the model.

## Derived maps

- **Normal** — Sobel-gradient normal map from the height map, with engine presets
  (OpenGL / Blender / Unity +Y, DirectX / Unreal −Y), strength, pre-smoothing, a
  multi-frequency mixer (macro / medium / micro detail) and optional photo-grain
  injection from the albedo.
- **Roughness** — estimated from local normal variance (Toksvig-style), with
  material presets, height-cavity and albedo-contrast blending, and a painter for
  hand-drawn wear, rust or glossy areas. This is a heuristic starting point, not a
  measurement of real surface roughness.
- **Ambient Occlusion** — ray-traced over the height field as a real 3D surface:
  you give its real-world scale (surface width and maximum depth) and each
  pixel's sky visibility is traced in 4–16 directions, so crevices darken by
  their actual depth and width and the result looks the same at any resolution.
  The original fast approximation remains available as the *Classic* method
  (projects saved before keep using it). Strength, contrast; 8- or 16-bit output, chosen when exporting.
- **Curvature** — exported alongside the other maps (optional, in the Export
  Maps dialog): mid-grey is flat, brighter marks edges and ridges, darker marks
  cavities; the usual mask for edge wear and dirt in material graphs.
- **Albedo** — used as imported, with optional auto white balance, color-range
  shifting and seamless edge blending.

Any map can also be imported directly instead of generated.

## 3D preview

Real-time OpenGL preview on a sphere, cube or plane using a Cook-Torrance / GGX
shader (albedo, normal, roughness, ambient occlusion), plus **Parallax Occlusion Mapping** driven
by the height map. Camera, lighting and display settings live in a separate View
Options panel. Double-click any map to inspect it in a 2×2 tiled view to check for
seams.
