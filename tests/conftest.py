from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest

from photoimporter.core.db import Database
from photoimporter.core.models import PhotoMeta

CARD_MTIME = 1_762_000_000  # even, like FAT timestamps


class FakeReader:
    """Metadata keyed by lowercase filename; unknown files have no EXIF."""

    def __init__(self, metas: dict[str, PhotoMeta] | None = None):
        self.metas = metas or {}
        self.read_count = 0

    def read(self, paths: Sequence[Path]) -> dict[Path, PhotoMeta]:
        self.read_count += len(paths)
        return {p: self.metas.get(p.name.lower(), PhotoMeta()) for p in paths}


def make_file(path: Path, content: bytes = b"photo", mtime: float = CARD_MTIME) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))
    return path


def copy_by_hand(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


RICOH = dict(make="RICOH IMAGING COMPANY, LTD.", model="RICOH GR III")
SONY = dict(make="SONY", model="DSC-RX100M7")


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "state" / "library.db")
    yield database
    database.close()


@pytest.fixture
def card(tmp_path: Path) -> Path:
    """A Ricoh card with a raw+jpg pair and a jpg-only shot, plus a video to ignore."""
    root = tmp_path / "card"
    dcim = root / "DCIM" / "100RICOH"
    make_file(dcim / "R0000001.JPG", b"jpg-1")
    make_file(dcim / "R0000001.DNG", b"raw-1-bigger")
    make_file(dcim / "R0000002.JPG", b"jpg-2")
    make_file(dcim / "R0000003.MOV", b"video")
    return root


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader(
        {
            "r0000001.jpg": PhotoMeta(**RICOH, capture_time="2026:11:02 10:00:00", subsec="12"),
            "r0000001.dng": PhotoMeta(**RICOH, capture_time="2026:11:02 10:00:00", subsec="12"),
            "r0000002.jpg": PhotoMeta(**RICOH, capture_time="2026:11:02 10:05:00"),
            "dsc00001.jpg": PhotoMeta(**SONY, capture_time="2026:11:02 11:00:00"),
            "dsc00001.arw": PhotoMeta(**SONY, capture_time="2026:11:02 11:00:00"),
        }
    )


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "Pictures"
    root.mkdir()
    return root
