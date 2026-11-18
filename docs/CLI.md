# Command line (for scripts and AI agents)

PBRCELAIN can generate maps without opening its window. Every command prints
**exactly one JSON object on stdout** and exits with `0` on success or `1` on
failure, even for usage mistakes. Progress and logs go to stderr. Results are
the same as the app's: the defaults and setting names come from the app itself.

## Running it

| Installed as | Command |
| --- | --- |
| macOS app | `/Applications/PBRCELAIN.app/Contents/MacOS/PBRCELAIN <command> …` |
| Windows app | `"%LOCALAPPDATA%\Programs\PBRCELAIN\PBRCELAIN.exe" <command> …` (installed for all users: `"%ProgramFiles%\PBRCELAIN\PBRCELAIN.exe"`) |
| From source | `python main.py <command> …` |

The examples below write `pbrcelain` for whichever of these applies.

The first `generate` that needs the AI depth model downloads the AI components
(packaged app only) and the model from Hugging Face. Both are cached for later
runs. On Windows with an NVIDIA graphics card the GPU (CUDA) version of the
components is downloaded (about 2 GB), otherwise the CPU version; `--device cpu`
or `PBRCELAIN_AI_VARIANT=cpu` picks the CPU version, and `--device cuda` replaces
an installed CPU version with the GPU one.

## Commands

### `generate`

```bash
pbrcelain generate photo.jpg --out maps/
```

Writes `height.png`, `normal.png`, `roughness.png` and `ao.png` into `maps/`
and answers:

```json
{
  "ok": true,
  "outputs": {
    "height": "/abs/path/maps/height.png",
    "normal": "/abs/path/maps/normal.png",
    "roughness": "/abs/path/maps/roughness.png",
    "ao": "/abs/path/maps/ao.png"
  },
  "resolution": [2048, 2048],
  "model": "Depth Anything V2",
  "size": "Small",
  "device": "mps",
  "seamless": false,
  "chunks": false,
  "seconds": 6.9
}
```

| Option | Meaning |
| --- | --- |
| `--out DIR`, `-o DIR` | Folder for the maps (required, created if missing). |
| `--maps LIST` | Comma-separated: `height`, `normal`, `roughness`, `ao`, `curvature`. Default: `height,normal,roughness,ao`. |
| `--height FILE` | Use an existing height map; skips the AI model entirely (fast, no download). |
| `--settings FILE` | Override settings with JSON from `pbrcelain settings`, or reuse a `.pcln` project's settings. |
| `--model NAME` | `Depth Anything V2` (default) or `Marigold`. |
| `--size NAME` | `Small`, `Base`, `Large` (Depth Anything) or `Fast`, `Standard` (Marigold). |
| `--device` | `auto` (default), `cpu`, `mps` (Apple Silicon), `cuda` (NVIDIA). |
| `--seamless` / `--no-seamless` | Make the height map (and everything derived from it) tileable. |
| `--chunks` / `--no-chunks` | Run the model in overlapping chunks: more detail on large images, slower. |
| `--height-bits` | `8`, `16` (default) or `32` (writes OpenEXR). |
| `--ao-bits` | `8` (default) or `16`. |

The albedo itself is written only when a settings file turns on an albedo
adjustment (white balance, color change or seamless).

### `settings`

```bash
pbrcelain settings > settings.json
```

Prints every setting with its default under `"settings"`, keyed by map:
`albedo`, `height`, `normal`, `roughness`, `ao`. Edit the values you need and
pass the file to `--settings` as is. A file holding only some maps or keys works
too; anything left out keeps its default.

### `models`

Lists the depth models, their sizes, checkpoints and **licenses**. Depth
Anything V2 Base and Large are non-commercial (CC BY-NC 4.0); use Small,
Marigold Fast or Marigold Standard for commercial work.

## Errors

```json
{ "ok": false, "error": "Unknown map(s): bogus. Choose from: height, normal, roughness, ao, curvature" }
```

The `error` text says what to change. Exit code is `1`.

## Tips for agents

- Check `ok` before reading `outputs`; paths in `outputs` are absolute.
- Use `--height` when a height map already exists: it avoids the model download
  and returns in about a second.
- For a tileable material, pass `--seamless`.
- Default model and settings are a good start; change one setting at a time
  with `--settings` and compare.
