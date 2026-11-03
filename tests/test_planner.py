from conftest import RICOH, SONY, make_file

from photoimporter.core.cards import scan_source
from photoimporter.core.models import Camera
from photoimporter.core.planner import build_plan


def test_new_photos_grouped_by_camera_with_jpg_and_raw_folders(tmp_path, card, reader):
    make_file(card / "DCIM" / "100MSDCF" / "DSC00001.JPG", b"sony-jpg")
    make_file(card / "DCIM" / "100MSDCF" / "DSC00001.ARW", b"sony-raw")
    photos = scan_source(card, reader)
    target = tmp_path / "Pictures" / "2026.11.02 Halloween Hike"
    cameras = {
        (RICOH["make"], RICOH["model"]): Camera(**RICOH, nickname="Ricoh", folder_name="ricoh")
    }

    plan = build_plan(card, target, photos, set(), cameras)

    assert plan.new_count == 5
    dests = {item.dest.relative_to(target).as_posix() for item in plan.items}
    assert dests == {
        "ricoh/jpg/R0000001.JPG",
        "ricoh/raw/R0000001.DNG",
        "ricoh/jpg/R0000002.JPG",
        "dsc-rx100m7/jpg/DSC00001.JPG",
        "dsc-rx100m7/raw/DSC00001.ARW",
    }
    assert [c.model for c in plan.unregistered] == [SONY["model"]]


def test_already_imported_photos_are_excluded(tmp_path, card, reader):
    photos = scan_source(card, reader)
    existing = {photos[0].key}

    plan = build_plan(card, tmp_path / "t", photos, existing, {})

    assert plan.new_count == 2
    assert plan.already_count == 1


def test_source_without_dcim_is_scanned_directly(tmp_path, reader):
    folder = tmp_path / "dump"
    make_file(folder / "R0000002.JPG")

    photos = scan_source(folder, reader)

    assert [p.filename for p in photos] == ["R0000002.JPG"]
