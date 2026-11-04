import os

import pytest
from conftest import make_file

from photoimporter.core.indexer import scan_library


def test_scan_indexes_only_photos(db, library, reader):
    make_file(library / "2026.10.01 Trip" / "ricoh" / "jpg" / "R0000001.JPG")
    make_file(library / "2026.10.01 Trip" / "ricoh" / "raw" / "R0000001.DNG")
    make_file(library / "2026.10.01 Trip" / "notes.txt")
    make_file(library / "2026.10.01 Trip" / "CaptureOne" / "Cache" / "thumb.cot")

    result = scan_library(db, library, reader)

    assert (result.added, result.updated, result.removed) == (2, 0, 0)
    assert db.file_count() == 2


def test_rescan_reads_only_changed_files(db, library, reader):
    a = make_file(library / "x" / "A.JPG", b"a")
    make_file(library / "x" / "B.JPG", b"b")
    scan_library(db, library, reader)
    reader.read_count = 0

    result = scan_library(db, library, reader)
    assert (result.added, result.updated, result.unchanged) == (0, 0, 2)
    assert reader.read_count == 0

    a.write_bytes(b"a-edited")
    os.utime(a, (5000, 5000))
    result = scan_library(db, library, reader)
    assert (result.updated, result.unchanged) == (1, 1)
    assert reader.read_count == 1


def test_deleted_files_move_to_history(db, library, reader):
    a = make_file(library / "x" / "R0000001.JPG")
    scan_library(db, library, reader)
    key = next(iter(db.existing_keys()))
    a.unlink()

    result = scan_library(db, library, reader)

    assert result.removed == 1
    assert db.file_count() == 0
    assert db.deleted_keys() == {key}
    assert db.newest_capture_by_model() == {"RICOH GR III": "2026:11:02 10:00:00"}


def test_restored_file_leaves_history(db, library, reader):
    a = make_file(library / "x" / "A.JPG", b"a")
    scan_library(db, library, reader)
    a.unlink()
    scan_library(db, library, reader)

    make_file(a, b"a")
    scan_library(db, library, reader)

    assert db.file_count() == 1
    assert db.deleted_count() == 0


def test_missing_library_folder_is_an_error_not_a_mass_delete(db, tmp_path, library, reader):
    make_file(library / "x" / "A.JPG")
    scan_library(db, library, reader)

    with pytest.raises(FileNotFoundError):
        scan_library(db, tmp_path / "unplugged", reader)
    library.rename(tmp_path / "moved")
    with pytest.raises(FileNotFoundError):
        scan_library(db, library, reader)

    assert db.file_count() == 1
    assert db.deleted_count() == 0


def test_scan_leaves_entries_outside_root_alone(db, tmp_path, library, reader):
    other = tmp_path / "Other"
    make_file(other / "A.JPG")
    scan_library(db, other, reader)

    scan_library(db, library, reader)

    assert db.file_count() == 1
