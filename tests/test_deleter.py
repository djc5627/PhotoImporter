import sys

import pytest
from conftest import make_file

from photoimporter.core.deleter import delete_from_card, windows_recycle


def card_files(tmp_path):
    return [
        make_file(tmp_path / "card" / "R0000001.JPG", b"jpg"),
        make_file(tmp_path / "card" / "R0000001.DNG", b"raw"),
    ]


def test_copies_are_recycled_before_the_card_files_are_removed(tmp_path):
    files = card_files(tmp_path)
    recycled = []

    def recycle(paths):
        for path in paths:
            assert path.read_bytes() in (b"jpg", b"raw")  # a full copy on the PC
            recycled.append(path.name)
            path.unlink()
        return set()

    result = delete_from_card(files, recycle, tmp_path / "deleted")

    assert sorted(recycled) == ["R0000001.DNG", "R0000001.JPG"]
    assert result.deleted == files and not result.failed
    assert not any(f.exists() for f in files)
    assert not result.kept_in.exists()  # emptied into the Recycle Bin


def test_files_stay_on_the_card_if_they_cannot_be_recycled(tmp_path):
    files = card_files(tmp_path)

    result = delete_from_card(files, lambda paths: set(paths), tmp_path / "deleted")

    assert result.deleted == []
    assert [f for f, _ in result.failed] == files
    assert all(f.exists() for f in files)


def test_without_a_recycle_bin_copies_stay_on_the_pc(tmp_path):
    files = card_files(tmp_path)

    result = delete_from_card(files, None, tmp_path / "deleted")

    assert not any(f.exists() for f in files)
    assert sorted(p.read_bytes() for p in result.kept_in.iterdir()) == [b"jpg", b"raw"]


def test_unreadable_file_is_reported_and_kept(tmp_path):
    files = card_files(tmp_path)
    missing = tmp_path / "card" / "GONE.JPG"

    result = delete_from_card([missing, *files], lambda paths: set(), tmp_path / "deleted")

    assert result.deleted == files
    assert [f for f, _ in result.failed] == [missing]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin")
def test_real_recycle_bin(tmp_path):
    path = make_file(tmp_path / "recycle me.jpg", b"x")
    assert windows_recycle([path]) == set()
    assert not path.exists()
