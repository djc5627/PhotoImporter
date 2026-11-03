import os

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


def test_deleted_files_are_pruned(db, library, reader):
    a = make_file(library / "x" / "A.JPG")
    scan_library(db, library, reader)
    a.unlink()

    result = scan_library(db, library, reader)

    assert result.removed == 1
    assert db.file_count() == 0


def test_scan_leaves_entries_outside_root_alone(db, tmp_path, library, reader):
    other = tmp_path / "Other"
    make_file(other / "A.JPG")
    scan_library(db, other, reader)

    scan_library(db, library, reader)

    assert db.file_count() == 1
