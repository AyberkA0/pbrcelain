# Releasing

PBRCELAIN uses semantic versioning (MAJOR.MINOR.PATCH). The version lives in one
place, `core/version.py`; the app, the CLI (`pbrcelain version`), the macOS
bundle, the Windows `.exe` properties and the AI runtime pack all read it there.

1. Bump `VERSION` in `core/version.py` and add a section to `CHANGELOG.md`.
2. Commit and push.
3. Build on each platform with its build environment (see below):

   ```bash
   python build_release.py
   ```

   This writes the app (`PBRCELAIN-<version>-macOS-AppleSilicon.dmg` or
   `PBRCELAIN-<version>-Windows-x64.zip`) and that platform's AI runtime pack
   into `release/`. The pack's download URL points at the `v<version>` release,
   so the version must not change between building and publishing.

4. Create the release from the macOS files, then add the Windows files:

   ```bash
   gh release create v<version> release/* --title "PBRCELAIN <version>" --notes-file <notes>
   gh release upload v<version> <the Windows files>
   ```

   The notes are `.github/release-notes.md` with `{version}` and `{changes}`
   (the version's CHANGELOG section) filled in.

## Build environments

Each platform's AI pack has compiled modules, so it must be built with the same
Python as that platform's app.

- **macOS (Apple Silicon):** Python with `requirements.txt` and `pyinstaller`.
- **Windows (x64):** Python with the CPU build of PyTorch first
  (`pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`),
  then `requirements.txt` and `pyinstaller`. PyTorch itself is not put in the
  pack: the manifest points at the official CPU and CUDA wheels on
  download.pytorch.org, and the app downloads the one the user picks.

The GitHub Actions workflow (`.github/workflows/release.yml`, run by hand) does
the same builds on GitHub's machines and keeps the files as workflow artifacts.
