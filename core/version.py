"""The PBRCELAIN version: the one place it is set.

Semantic versioning, MAJOR.MINOR.PATCH. The build scripts, the app bundle,
the AI runtime pack and the CLI all read it from here, and a release is
tagged v<VERSION>. Bump it (and add a CHANGELOG.md entry) before a release.
"""

VERSION = "0.68.1"
TAG = f"v{VERSION}"
