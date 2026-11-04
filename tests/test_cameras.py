from conftest import RICOH, make_file

from photoimporter.core.cameras import LibraryLayout
from photoimporter.core.indexer import scan_library


def test_suggests_most_used_folders_for_a_model(db, library, reader):
    for day, folder in (("2025.01.01 A", "gr3"), ("2025.02.01 B", "gr3"), ("2025.03.01 C", "x")):
        make_file(library / day / folder / "JPEG" / "R0000001.JPG")
        make_file(library / day / folder / "RAW" / "R0000001.DNG")
    make_file(library / "4.1.2025 Hand copied" / "R0000002.JPG")  # no camera folder
    scan_library(db, library, reader)

    layout = LibraryLayout.from_db(db, library)

    assert layout.camera_folders == ["gr3", "x"]
    camera, matched = layout.suggest(RICOH["make"], RICOH["model"])
    assert matched
    assert (camera.folder_name, camera.jpg_dir, camera.raw_dir) == ("gr3", "JPEG", "RAW")


def test_unknown_model_gets_default_folders(db, library):
    camera, matched = LibraryLayout.from_db(db, library).suggest("SONY", "ILCE-7RM5")

    assert not matched
    assert (camera.folder_name, camera.jpg_dir, camera.raw_dir) == ("ilce-7rm5", "jpg", "raw")
