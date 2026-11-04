"""Print the CHANGELOG.md section for a release tag, after checking the tag matches the app.

    python packaging/release_notes.py v1.0.0 > notes.md

Fails if the tag isn't `v<photoimporter.__version__>` or CHANGELOG.md has no section for it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def app_version(root: Path = ROOT) -> str:
    text = (root / "src" / "photoimporter" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("__version__ not found in src/photoimporter/__init__.py")
    return match.group(1)


def changelog_section(changelog: str, version: str) -> str:
    """The body of the `## [version]` section, without its heading."""
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(changelog)
    if not match:
        raise ValueError(f"CHANGELOG.md has no '## [{version}]' section")
    following = re.compile(r"^## ", re.MULTILINE).search(changelog, match.end())
    body = changelog[match.end() : following.start() if following else len(changelog)]
    if not body.strip():
        raise ValueError(f"The CHANGELOG.md section for {version} is empty")
    return body.strip() + "\n"


def release_notes(tag: str, root: Path = ROOT) -> str:
    version = app_version(root)
    if tag != f"v{version}":
        raise ValueError(
            f"Tag {tag} doesn't match the app version {version}. "
            "Update __version__ in src/photoimporter/__init__.py first."
        )
    return changelog_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), version)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        sys.stdout.write(release_notes(sys.argv[1]))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
