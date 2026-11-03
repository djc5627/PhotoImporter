from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

JPG_EXTS = frozenset({".jpg", ".jpeg"})
RAW_EXTS = frozenset({".dng", ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf", ".rw2", ".pef"})
PHOTO_EXTS = JPG_EXTS | RAW_EXTS

PhotoKey = tuple[str, str, str]


def file_kind(ext: str) -> str | None:
    ext = ext.lower()
    if ext in JPG_EXTS:
        return "jpg"
    if ext in RAW_EXTS:
        return "raw"
    return None


def is_photo(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in PHOTO_EXTS


def norm_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(path))


@dataclass(frozen=True)
class PhotoMeta:
    make: str | None = None
    model: str | None = None
    capture_time: str | None = None
    subsec: str | None = None


def photo_key(filename: str, mtime: float, meta: PhotoMeta) -> PhotoKey:
    """Identity used to decide whether a card photo is already in the library."""
    if meta.capture_time:
        when = meta.capture_time + (f".{meta.subsec}" if meta.subsec else "")
    else:
        # FAT cards store mtime with 2-second resolution.
        when = f"mtime:{int(mtime) // 2 * 2}"
    return ((meta.model or "").strip(), filename.lower(), when)


@dataclass(frozen=True)
class PhotoFile:
    path: Path
    size: int
    mtime: float
    meta: PhotoMeta

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def kind(self) -> str | None:
        return file_kind(self.path.suffix)

    @property
    def key(self) -> PhotoKey:
        return photo_key(self.filename, self.mtime, self.meta)


_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_name(name: str) -> str:
    cleaned = _INVALID_FOLDER_CHARS.sub("_", name).strip(" .")
    return cleaned or "unknown camera"


@dataclass
class Camera:
    make: str
    model: str
    nickname: str
    folder_name: str
    jpg_dir: str = "jpg"
    raw_dir: str = "raw"

    @classmethod
    def default_for(cls, make: str, model: str) -> Camera:
        name = model or make or "unknown camera"
        return cls(
            make=make, model=model, nickname=name, folder_name=safe_folder_name(name.lower())
        )

    def subdir_for(self, kind: str | None) -> str:
        return self.raw_dir if kind == "raw" else self.jpg_dir
