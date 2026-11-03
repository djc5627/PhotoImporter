from __future__ import annotations

import os
import string
from pathlib import Path

from .exif import MetadataReader, Progress, read_metadata
from .indexer import iter_photo_files
from .models import PhotoFile


def detect_cards() -> list[Path]:
    """Drives (other than the system drive) that have a DCIM folder."""
    if hasattr(os, "listdrives"):
        drives = os.listdrives()
    else:
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase]
    system_drive = os.environ.get("SystemDrive", "C:").upper()
    cards = []
    for drive in drives:
        path = Path(drive)
        if path.drive.upper() in ("A:", "B:", system_drive):
            continue
        try:
            if (path / "DCIM").is_dir():
                cards.append(path)
        except OSError:
            continue
    return cards


def photo_root(source: Path) -> Path:
    dcim = source / "DCIM"
    return dcim if dcim.is_dir() else source


def scan_source(
    source: Path, reader: MetadataReader, progress: Progress | None = None
) -> list[PhotoFile]:
    entries = sorted(iter_photo_files(photo_root(source)), key=lambda e: e.path)
    paths = [Path(e.path) for e in entries]
    metas = read_metadata(reader, paths, progress)
    photos = []
    for entry, path in zip(entries, paths, strict=True):
        stat = entry.stat()
        photos.append(PhotoFile(path, stat.st_size, stat.st_mtime, metas[path]))
    return photos
