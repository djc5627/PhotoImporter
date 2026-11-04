"""Thumbnails for the preview grid: shots (RAW+JPG pairs) and embedded preview images."""

from __future__ import annotations

import base64
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .exif import find_exiftool, match_records, run_exiftool
from .models import PhotoFile


@dataclass
class Shot:
    """One picture: a JPG, a RAW, or a RAW+JPG pair taken together."""

    photos: list[PhotoFile] = field(default_factory=list)

    @property
    def primary(self) -> PhotoFile:
        """The file to take the thumbnail from: the JPG if there is one."""
        return next((p for p in self.photos if p.kind == "jpg"), self.photos[0])

    @property
    def kinds(self) -> set[str]:
        return {p.kind or "other" for p in self.photos}

    @property
    def badge(self) -> str:
        if self.kinds >= {"jpg", "raw"}:
            return "RAW+JPG"
        return "RAW" if "raw" in self.kinds else ""

    @property
    def name(self) -> str:
        return self.primary.path.stem

    @property
    def capture_time(self) -> str | None:
        return self.primary.meta.capture_time

    @property
    def sort_time(self) -> str:
        """When the shot was taken, as 'YYYY:MM:DD HH:MM:SS[.subsec]', for sorting.

        Uses the file's date when there is no EXIF capture time.
        """
        meta = self.primary.meta
        when = meta.capture_time or time.strftime(
            "%Y:%m:%d %H:%M:%S", time.localtime(self.primary.mtime)
        )
        return when + (f".{meta.subsec}" if meta.subsec else "")


def _shot_key(photo: PhotoFile) -> tuple[str, str, str]:
    when = photo.meta.capture_time or f"mtime:{int(photo.mtime) // 2 * 2}"
    if photo.meta.subsec:
        when += f".{photo.meta.subsec}"
    return (str(photo.path.parent).lower(), photo.path.stem.lower(), when)


def group_shots(photos: Iterable[PhotoFile]) -> list[Shot]:
    """Pair files of the same shot (same folder, name and time), newest first."""
    shots: dict[tuple[str, str, str], Shot] = {}
    for photo in photos:
        shots.setdefault(_shot_key(photo), Shot()).photos.append(photo)
    return sorted(shots.values(), key=lambda s: (s.sort_time, s.name.lower()), reverse=True)


@dataclass(frozen=True)
class Thumbnail:
    data: bytes | None  # an encoded (usually JPEG) image, or None if the file has none
    orientation: int = 1  # EXIF Orientation of the photo the thumbnail belongs to


class ThumbnailSource(Protocol):
    def extract(self, paths: Sequence[Path], large: bool = False) -> dict[Path, Thumbnail]:
        """Embedded previews of `paths`; `large` prefers the bigger preview image."""
        ...


def _binary(value: object) -> bytes | None:
    if isinstance(value, str) and value.startswith("base64:"):
        try:
            return base64.b64decode(value[len("base64:") :])
        except ValueError:
            return None
    return None


def _orientation(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


class ExifToolThumbnails:
    """Reads the small preview images cameras embed in JPG and RAW files.

    These are a few kilobytes at the start of each file, so a card's worth loads quickly
    without reading whole photos. Files without one get `data=None`.
    """

    def __init__(self, exe: str | None = None):
        self.exe = exe or find_exiftool()

    def extract(self, paths: Sequence[Path], large: bool = False) -> dict[Path, Thumbnail]:
        """The small ThumbnailImage (about 160×120), or with `large` the bigger PreviewImage.

        Each falls back to the other when a file lacks it: some RAW formats only carry a
        PreviewImage, and many JPGs only a ThumbnailImage.
        """
        if not paths:
            return {}
        first, second = (
            ("PreviewImage", "ThumbnailImage")
            if large
            else (
                "ThumbnailImage",
                "PreviewImage",
            )
        )
        records, _, _ = run_exiftool(self.exe, ["-b", "-n", f"-{first}", "-Orientation"], paths)
        found = match_records(paths, records)
        result = {
            path: Thumbnail(_binary(rec.get(first)), _orientation(rec.get("Orientation")))
            for path, rec in found.items()
        }
        missing = [p for p in paths if result.get(p) is None or result[p].data is None]
        if missing:
            records, _, _ = run_exiftool(self.exe, ["-b", "-n", f"-{second}"], missing)
            for path, rec in match_records(missing, records).items():
                data = _binary(rec.get(second))
                if data:
                    orientation = result[path].orientation if path in result else 1
                    result[path] = Thumbnail(data, orientation)
        for path in paths:
            result.setdefault(path, Thumbnail(None))
        return result
