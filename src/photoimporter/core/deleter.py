"""Delete photos from the SD card without losing them for good.

SD cards have no Recycle Bin, so each file is first copied to a folder on this PC, that copy is
sent to the Windows Recycle Bin, and only then is the file removed from the card. Restoring
from the Recycle Bin puts the photo back in that folder on the PC (not on the card).
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .exif import Progress

# Sends files to the Recycle Bin; returns the ones that couldn't be recycled.
Recycler = Callable[[Sequence[Path]], set[Path]]


def staging_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "PhotoImporter" / "Deleted from card"


@dataclass
class DeleteResult:
    deleted: list[Path] = field(default_factory=list)  # card paths now gone from the card
    failed: list[tuple[Path, str]] = field(default_factory=list)
    kept_in: Path | None = None  # where restored files go (or where they are, without a bin)


def windows_recycle(paths: Sequence[Path]) -> set[Path]:
    """Send local files to the Recycle Bin in one operation (undoable from Explorer)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    fo_delete = 0x0003
    fof_silent, fof_noconfirmation, fof_allowundo = 0x0004, 0x0010, 0x0040
    fof_noerrorui, fof_wantnukewarning = 0x0400, 0x4000
    op = SHFILEOPSTRUCTW()
    op.wFunc = fo_delete
    op.pFrom = "\0".join(str(p) for p in paths) + "\0\0"
    # Ask before deleting anything that is too big for the Recycle Bin.
    op.fFlags = (
        fof_silent | fof_noconfirmation | fof_allowundo | fof_noerrorui | fof_wantnukewarning
    )
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return {p for p in paths if p.exists()}


def default_recycler() -> Recycler | None:
    return windows_recycle if sys.platform == "win32" else None


def _free_name(folder: Path, name: str) -> Path:
    candidate, n = folder / name, 1
    while candidate.exists():
        stem, suffix = os.path.splitext(name)
        candidate = folder / f"{stem}_{n}{suffix}"
        n += 1
    return candidate


def delete_from_card(
    paths: Sequence[Path],
    recycle: Recycler | None = None,
    staging: Path | None = None,
    progress: Progress | None = None,
) -> DeleteResult:
    """Remove `paths` from the card, keeping a recoverable copy of each.

    With `recycle`, the copies go to the Recycle Bin; without one (e.g. not on Windows) they
    stay in the staging folder.
    """
    folder = (staging or staging_root()) / datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    result = DeleteResult(kept_in=folder)
    copies: dict[Path, Path] = {}
    total = len(paths) * 2
    folder.mkdir(parents=True, exist_ok=True)
    for done, path in enumerate(paths, 1):
        try:
            copy = _free_name(folder, path.name)
            shutil.copy2(path, copy)
            if copy.stat().st_size != path.stat().st_size:
                copy.unlink()
                raise OSError("the copy on this PC is incomplete")
            copies[path] = copy
        except OSError as exc:
            result.failed.append((path, f"not deleted: {exc}"))
        if progress:
            progress(done, total)

    not_recycled: set[Path] = set()
    if recycle is not None and copies:
        not_recycled = recycle(list(copies.values()))

    for done, (path, copy) in enumerate(copies.items(), len(paths) + 1):
        if copy in not_recycled:
            copy.unlink(missing_ok=True)
            result.failed.append((path, "not deleted: it couldn't be moved to the Recycle Bin"))
        else:
            try:
                path.unlink()
                result.deleted.append(path)
            except OSError as exc:
                result.failed.append((path, f"not deleted from the card: {exc}"))
        if progress:
            progress(done, total)
    try:
        folder.rmdir()  # empty once everything went to the Recycle Bin
    except OSError:
        pass
    return result
