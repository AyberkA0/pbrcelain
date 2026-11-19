<p align="center">
  <img src="ui/assets/app_icon.png" alt="PBRCELAIN logo" width="160">
</p>

<h1 align="center">PBRCELAIN</h1>

<p align="center">
  <strong>Turn a single photo into a clean, tileable height map — and a full PBR material around it.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/4K-supported-4a72d9?style=flat-square" alt="4K">
  <img src="https://img.shields.io/badge/8K-supported-4a72d9?style=flat-square" alt="8K">
  <img src="https://img.shields.io/badge/resolution-unlimited-4a72d9?style=flat-square" alt="Unlimited resolution">
  <img src="https://img.shields.io/badge/output-seamless%20%26%20tileable-4a72d9?style=flat-square" alt="Seamless and tileable">
</p>

<p align="center">
  <a href="https://github.com/AyberkA0/pbrcelain/releases"><img src="https://img.shields.io/badge/Download-macOS%20%7C%20Windows-0a84ff?style=for-the-badge" alt="Download for macOS or Windows"></a>
</p>

<p align="center">
  <a href="https://buymeabitcoffee.vercel.app/btc/bc1qhae9un6j8mel5xcrd4trajm65wfunlltkzelh7?identifier=Buy+Me+a+Coffee"><img src="https://img.shields.io/badge/☕%20Buy%20Me%20a%20Coffee-Donate-f7931a?style=for-the-badge&logo=bitcoin&logoColor=white" alt="Buy Me a Coffee"></a>
</p>

<p align="center">
  <img src="docs/media/app-window.png" alt="PBRCELAIN main window on macOS: material slots and map settings on the left, 3D viewport on the right" width="760">
</p>

PBRCELAIN is a free desktop app that turns an ordinary photo of a surface (stone,
brick, wood, tiles, fabric…) into the texture maps a game engine or 3D renderer
needs: **Height, Normal, Roughness and Ambient Occlusion**. An AI depth model
estimates the relief from the photo, the other maps are built from it, and you see
the result live on a 3D preview.

https://github.com/user-attachments/assets/ccbf458e-5fbc-4bad-85d3-8ebc7d6a2fc8

## Showcase

Materials generated from single photos, previewed in the built-in 3D viewport.

<p align="center">
  <img src="docs/media/mossy-ground.gif" alt="Mossy ground material rotating in the 3D viewport" width="520"><br>
  <em>Mossy ground</em> (1254x1254)
</p>

<p align="center">
  <img src="docs/media/strange-pebbles.gif" alt="Strange pebbles material rotating in the 3D viewport" width="520"><br>
  <em>Strange pebbles</em> (1254x1254)
</p>

<p align="center">
  <img src="docs/media/porcelain.gif" alt="Broken blue-and-white porcelain tiles rotating in the 3D viewport" width="520"><br>
  <em>Porcelain</em> (1254x1254)
</p>

## Download

Ready-to-run builds for **macOS (Apple Silicon)** and **Windows (64-bit)** are on the
[Releases page](https://github.com/AyberkA0/pbrcelain/releases) — no Python needed.
The app itself is a small download; the AI components are downloaded once, the
first time you generate a Height map. On Windows with an NVIDIA graphics card you
can pick the GPU (CUDA) version, about 2 GB, which runs the depth models much
faster; the CPU version is about 180 MB. On a Mac they run on the GPU (about 160 MB).

Windows builds are to be signed with free code signing provided by
[SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org) (application pending; current builds are
unsigned). See the [code signing policy](docs/CODE_SIGNING.md).

### First launch on macOS

The app is not notarized by Apple yet, so macOS blocks it the first time:

1. Open the DMG and drag **PBRCELAIN** into **Applications**.
2. Open it once. When macOS says it cannot verify the app, click **Done**.
3. Go to **System Settings › Privacy & Security**, scroll down and click
   **Open Anyway** next to PBRCELAIN, then confirm.

You only need to do this once. If macOS instead says the app **is damaged**, run
this in Terminal and open it again:

```bash
xattr -dr com.apple.quarantine /Applications/PBRCELAIN.app
```

## Getting started

1. **Import a photo** into the Albedo slot (the one that pulses).
2. Select the **Height** slot and click **Generate Height**. The first run
   downloads the AI components and the depth model.
3. Generate **Normal**, **Roughness** and **Ambient Occlusion** the same way, fine-tune them on the
   **Adjustment** page, then use **Export** to write every map to a folder.

Hover over any setting to see what it does. Projects are saved as `.pcln` files that
keep everything, so you can reopen and keep adjusting without re-running the model.

## Which depth model?

> [!IMPORTANT]
> The right model makes the biggest difference to the result.
>
> - **Depth Anything V2**: deep, uneven surfaces with lots of relief, like pebbles,
>   gravel, rocks, bark and rubble.
> - **Marigold**: flatter, regular, patterned surfaces, like tiles, pavers, brick
>   walls, planks and fabric.
>
> Switch it in **Height › Depth Model**. If a result looks off, try the other one.

## 4K, 8K and beyond

General image AIs work at a small, fixed output size, so a 4K or 8K photo loses its
fine relief. PBRCELAIN's **Full Resolution with Chunk Estimation** runs the depth model over the
photo in overlapping chunks, so the height map keeps your photo's full resolution,
with no upper limit, and stays as accurate as the AI model.

## Use from scripts and AI agents

PBRCELAIN also runs without its window, so scripts and LLM agents (Claude Code,
Cursor, Codex…) can generate maps with one command and read a JSON answer:

```bash
PBRCELAIN generate photo.jpg --out maps/
```

No extra setup: it is the same app binary (on macOS,
`/Applications/PBRCELAIN.app/Contents/MacOS/PBRCELAIN`). See the
[command line guide](docs/CLI.md) for every option.

## Learn more

- [How it works](docs/HOW-IT-WORKS.md): the depth models, high-resolution and seamless
  generation, artifact correction, and how each map is derived.
- [Command line](docs/CLI.md): generating maps from scripts and AI agents.
- [Running from source](docs/DEVELOPMENT.md): installing with Python, GPU setup,
  file associations and project file details.
- [Changelog](CHANGELOG.md): what changed in each version.
- [Code signing policy](docs/CODE_SIGNING.md): how Windows builds are signed, and what
  the app sends over the network (nothing about you).

## License

PBRCELAIN is free software under the [GNU General Public License v3.0](LICENSE).

The depth models are downloaded from Hugging Face and come with their own licenses.
**Depth Anything V2 Base and Large are licensed for non-commercial use only**
(CC BY-NC 4.0). For commercial work, use Depth Anything V2 Small (Apache 2.0),
Marigold Fast (Apache 2.0) or Marigold Standard (CreativeML Open RAIL++-M).
