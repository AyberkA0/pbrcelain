# Code signing policy

Windows builds of PBRCELAIN are to be signed through the SignPath Foundation:
free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org). The application is
pending; until it is approved, Windows releases are unsigned.

## What is signed

Only release builds of PBRCELAIN for Windows (`PBRCELAIN-<version>-Windows-x64.zip`
from the [Releases page](https://github.com/AyberkA0/pbrcelain/releases)). They
are built from this repository's source by the GitHub Actions workflow
[`.github/workflows/release.yml`](../.github/workflows/release.yml), and only those
workflow builds are submitted for signing. Builds made anywhere else are never
signed.

## Team roles

| Role | Members |
| --- | --- |
| Committers and reviewers | [AyberkA0](https://github.com/AyberkA0) |
| Approvers | [AyberkA0](https://github.com/AyberkA0) |

Every signing request is approved by hand.

## Privacy policy

PBRCELAIN does not collect, store or send any personal or usage data, and has no
telemetry. It connects to the internet only to download components the user
asks for, the first time they are needed:

- the AI runtime pack, from this repository's GitHub releases;
- on Windows, PyTorch (CPU or NVIDIA GPU build), from download.pytorch.org;
- the depth models, from Hugging Face.

Those services' own privacy policies apply to those downloads.
