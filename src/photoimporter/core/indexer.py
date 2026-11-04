from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .db import Database
from .exif import MetadataReader, Progress, read_metadata
from .models import PhotoFile, is_photo, norm_path


def iter_photo_files(root: Path) -> Iterator[os.DirEntry[str]]:
    stack = [str(root)]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif is_photo(entry.name) and entry.is_file():
                    yield entry
            except OSError:
                continue


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0


def scan_library(
    db: Database, root: Path, reader: MetadataReader, progress: Progress | None = None
) -> ScanResult:
    """Bring the index in sync with `root`, reading metadata only for new or changed files.

    Files that have disappeared are remembered as deleted rather than forgotten, so photos
    removed from the library (e.g. in Capture One) are not offered for import again.
    """
    if not root.is_dir():
        # Without this, an unplugged drive would look like every photo had been deleted.
        raise FileNotFoundError(f"Photo library folder not found: {root}")
    prefix = norm_path(root).rstrip("\\/") + os.sep
    known = {p: st for p, st in db.file_stats().items() if p.startswith(prefix)}
    result = ScanResult()
    seen: set[str] = set()
    pending: list[tuple[Path, int, float]] = []

    for entry in iter_photo_files(root):
        path = norm_path(entry.path)
        stat = entry.stat()
        seen.add(path)
        current = (stat.st_size, stat.st_mtime)
        previous = known.get(path)
        if previous == current:
            result.unchanged += 1
            continue
        if previous is None:
            result.added += 1
        else:
            result.updated += 1
        pending.append((Path(path), *current))

    removed = [p for p in known if p not in seen]
    db.mark_deleted(removed)
    result.removed = len(removed)

    metas = read_metadata(reader, [p for p, _, _ in pending], progress)
    db.upsert_files(PhotoFile(p, size, mtime, metas[p]) for p, size, mtime in pending)
    return result
