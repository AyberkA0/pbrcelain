# Releasing

PBRCELAIN uses semantic versioning (MAJOR.MINOR.PATCH). The version lives in one
place, `core/version.py`; the app, the CLI (`pbrcelain version`), the macOS
bundle, the Windows `.exe` properties and the AI runtime pack all read it there.

1. Bump `VERSION` in `core/version.py` and add a section to `CHANGELOG.md`.
2. Commit and push.
3. Run the **Release builds** workflow on GitHub Actions and download its two
   artifacts (`release-macOS`, `release-Windows`):

   ```bash
   gh workflow run release.yml --ref main
   gh run download <run id> -D release
   ```

   They hold the app (`PBRCELAIN-<version>-macOS-AppleSilicon.dmg`,
   `PBRCELAIN-<version>-Windows-x64-Setup.exe`) and each platform's AI runtime
   pack. The packs' download URLs point at the `v<version>` release, so the
   version must not change between building and publishing. (`python
   build_release.py` makes the same files on a local machine, but only CI builds
   can be code signed.)

4. Tag the commit that was built, and create the release with all four files:

   ```bash
   git tag -a v<version> -m "PBRCELAIN <version>" <commit> && git push origin v<version>
   gh release create v<version> release/*/* --title "PBRCELAIN <version>" --notes-file <notes>
   ```

   The notes are `.github/release-notes.md` with `{version}` and `{changes}`
   (the version's CHANGELOG section) filled in.

## Build environments

Each platform's AI pack has compiled modules, so it must be built with the same
Python as that platform's app.

- **macOS (Apple Silicon):** Python with `requirements.txt` and `pyinstaller`.
- **Windows (x64):** Python with the CPU build of PyTorch first
  (`pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`),
  then `requirements.txt` and `pyinstaller`, and [Inno Setup 6](https://jrsoftware.org/isdl.php)
  for the installer (`installer/pbrcelain.iss`). PyTorch itself is not put in the
  pack: the manifest points at the official CPU and CUDA wheels on
  download.pytorch.org, and the app downloads the one the user picks.

The GitHub Actions workflow (`.github/workflows/release.yml`, run by hand) does
the same builds on GitHub's machines and keeps the files as workflow artifacts.
