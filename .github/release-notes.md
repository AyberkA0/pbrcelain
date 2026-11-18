## Downloads

| Platform | File |
| --- | --- |
| macOS (Apple Silicon, M1 and later) | `PBRCELAIN-{version}-macOS-AppleSilicon.dmg` |
| Windows 10/11 (64-bit) | `PBRCELAIN-{version}-Windows-x64.zip` |

No Python installation needed. The `PBRCELAIN-ai-runtime-…` files are downloaded
by the app itself the first time you generate a Height map; you don't need to
download them. Depth models come from Hugging Face on first use (about 100 MB for
Depth Anything V2 Small, up to a few GB for the larger models) and are cached.

**macOS:** open the DMG and drag `PBRCELAIN.app` to Applications. The app is not
notarized yet: open it once, click **Done**, then go to **System Settings ›
Privacy & Security** and click **Open Anyway**. If macOS says the app is damaged,
run `xattr -dr com.apple.quarantine /Applications/PBRCELAIN.app` once. Depth
estimation runs on the GPU (Metal/MPS).

**Windows:** unzip anywhere and run `PBRCELAIN.exe`. SmartScreen may ask for
confirmation (**More info › Run anyway**) since the build is unsigned. With an
NVIDIA graphics card, the app offers the GPU (CUDA) version of the AI components
on first use (about 2 GB, downloaded from PyTorch); otherwise it downloads the CPU
version (about 180 MB). Windows builds are to be signed with free code signing
provided by SignPath.io, certificate by SignPath Foundation (application pending;
see the [code signing policy](https://github.com/AyberkA0/pbrcelain/blob/main/docs/CODE_SIGNING.md)).

## What's new

{changes}
