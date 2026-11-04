import importlib.util
from pathlib import Path

import pytest

import photoimporter

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "release_notes", ROOT / "packaging" / "release_notes.py"
)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

## [1.1.0] - 2026-12-01
### Fixed
- Something.

## [1.0.0] - 2026-11-04
First release.
"""


def test_section_is_extracted():
    assert release_notes.changelog_section(CHANGELOG, "1.1.0") == "### Fixed\n- Something.\n"
    assert release_notes.changelog_section(CHANGELOG, "1.0.0") == "First release.\n"
    with pytest.raises(ValueError, match="no '## \\[2.0.0\\]' section"):
        release_notes.changelog_section(CHANGELOG, "2.0.0")


def test_current_version_has_release_notes():
    """Keeps CHANGELOG.md in step with __version__, so a release can always be made."""
    version = photoimporter.__version__
    assert release_notes.app_version() == version
    assert release_notes.release_notes(f"v{version}").strip()


def test_tag_must_match_app_version():
    with pytest.raises(ValueError, match="doesn't match the app version"):
        release_notes.release_notes("v0.0.1")
