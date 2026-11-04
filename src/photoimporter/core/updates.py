"""Check GitHub for a newer release. Only reads public release info; never downloads or installs."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import __version__

REPO = "djc5627/PhotoImporter"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
_LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


@dataclass(frozen=True)
class Release:
    version: str  # e.g. "1.0.1"
    page_url: str  # the release page, with its change log
    installer_url: str | None


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Anything after the numbers (e.g. '-beta') is ignored."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_newer(candidate: str, current: str | None = None) -> bool:
    """Whether `candidate` is a later version than `current` (default: this app)."""
    new, old = parse_version(candidate), parse_version(current or __version__)
    width = max(len(new), len(old))
    return bool(new) and new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def parse_release(data: dict) -> Release | None:
    tag = data.get("tag_name") or ""
    if not parse_version(tag) or data.get("draft") or data.get("prerelease"):
        return None
    installer = next(
        (
            asset.get("browser_download_url")
            for asset in data.get("assets") or []
            if str(asset.get("name", "")).lower().endswith("-setup.exe")
        ),
        None,
    )
    version = ".".join(map(str, parse_version(tag)))
    return Release(version, data.get("html_url") or RELEASES_PAGE, installer)


def fetch_latest_release(timeout: float = 10) -> Release | None:
    """The latest published release, or None if there is none. Raises OSError when offline."""
    request = urllib.request.Request(
        _LATEST_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"PhotoImporter/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return parse_release(json.load(response))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no releases yet
            return None
        raise


def newer_release(timeout: float = 10) -> Release | None:
    """The latest release if it is newer than this app, else None."""
    release = fetch_latest_release(timeout)
    return release if release is not None and is_newer(release.version) else None
