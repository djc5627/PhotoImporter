import json
import urllib.error
import urllib.request

import pytest

from photoimporter.core import updates
from photoimporter.core.updates import Release, is_newer, newer_release, parse_release


@pytest.mark.parametrize(
    "candidate, current, expected",
    [
        ("v1.0.1", "1.0.0", True),
        ("1.10.0", "1.9.3", True),
        ("v2", "1.9.9", True),
        ("1.0", "1.0.0", False),
        ("v0.9.9", "1.0.0", False),
        ("nonsense", "1.0.0", False),
    ],
)
def test_is_newer(candidate, current, expected):
    assert is_newer(candidate, current) is expected


def test_parse_release_finds_the_installer():
    data = {
        "tag_name": "v1.2.0",
        "html_url": "https://github.com/djc5627/PhotoImporter/releases/tag/v1.2.0",
        "assets": [
            {"name": "PhotoImporter-1.2.0-portable.zip", "browser_download_url": "zip"},
            {"name": "PhotoImporter-1.2.0-setup.exe", "browser_download_url": "exe"},
        ],
    }
    assert parse_release(data) == Release("1.2.0", data["html_url"], "exe")
    assert parse_release({**data, "prerelease": True}) is None


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def read(self, *args):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_newer_release_only_when_newer(monkeypatch):
    monkeypatch.setattr(updates, "__version__", "1.0.0")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout: FakeResponse({"tag_name": "v1.0.0"})
    )
    assert newer_release() is None
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout: FakeResponse({"tag_name": "v1.1.0"})
    )
    assert newer_release().version == "1.1.0"


def test_no_releases_yet_is_not_an_error(monkeypatch):
    def not_found(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    assert newer_release() is None
