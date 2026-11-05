from pathlib import Path

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


def _by_name(photos):
    return sorted(p.filename for p in photos)


def test_photos_deleted_since_import_are_skipped_unless_included(tmp_path, card, reader):
    photos = scan_source(card, reader)
    jpg = next(p for p in photos if p.filename == "R0000001.JPG")

    plan = build_plan(card, tmp_path / "t", photos, set(), {}, deleted_keys={jpg.key})

    assert (plan.new_count, plan.deleted_count, plan.copy_count) == (2, 1, 2)
    assert _by_name(i.photo for i in plan.items) == ["R0000001.DNG", "R0000002.JPG"]
    assert plan.summary() == (
        "2 new photos · 0 already imported · 1 deleted since import (skipped)"
    )

    plan.include_deleted = True
    assert plan.copy_count == 3
    assert "1 deleted since import (included)" in plan.summary()


def test_deleted_photos_newer_than_library_are_recent(tmp_path, card, reader):
    photos = scan_source(card, reader)
    deleted = {p.key for p in photos}
    present = {"RICOH GR III": "2026:11:02 10:00:00"}

    plan = build_plan(
        card, tmp_path / "t", photos, set(), {}, deleted, newest_present_by_model=present
    )

    group = plan.groups[0]
    assert _by_name(group.recent_deleted) == ["R0000002.JPG"]  # 10:05
    assert _by_name(group.deleted) == ["R0000001.DNG", "R0000001.JPG"]  # 10:00, not newer
    plan.include_recent_deleted = True
    assert _by_name(i.photo for i in plan.items) == ["R0000002.JPG"]
    assert "1 recently deleted (included) · 2 deleted since import (skipped)" in plan.summary()


def test_photo_still_in_library_wins_over_deleted_history(tmp_path, card, reader):
    photos = scan_source(card, reader)
    keys = {p.key for p in photos}

    plan = build_plan(card, tmp_path / "t", photos, keys, {}, deleted_keys=keys)

    assert (plan.already_count, plan.deleted_count) == (3, 0)


def test_photos_older_than_newest_library_photo_are_probably_deleted(tmp_path, card, reader):
    make_file(card / "DCIM" / "100RICOH" / "R0000009.JPG", b"no-exif")
    photos = scan_source(card, reader)
    # The library's newest Ricoh shot is between R0000001 (10:00) and R0000002 (10:05).
    newest = {"RICOH GR III": "2026:11:02 10:03:00"}

    plan = build_plan(card, tmp_path / "t", photos, set(), {}, newest_by_model=newest)

    group = plan.groups[0]
    assert _by_name(group.older) == ["R0000001.DNG", "R0000001.JPG"]
    assert _by_name(plan.groups[1].new) == ["R0000009.JPG"]  # no capture time: can't tell
    assert _by_name(group.new) == ["R0000002.JPG"]
    assert plan.copy_count == 2

    plan.include_older = True
    assert plan.copy_count == 4


def test_older_rule_is_per_camera(tmp_path, card, reader):
    photos = scan_source(card, reader)

    plan = build_plan(
        card, tmp_path / "t", photos, set(), {}, newest_by_model={"DSC-RX100M7": "2030:01:01"}
    )

    assert (plan.new_count, plan.older_count) == (3, 0)


def test_import_breakdown_counts_pictures_per_camera_and_status(tmp_path, card, reader):
    from photoimporter.core.planner import import_breakdown

    make_file(card / "DCIM" / "100MSDCF" / "DSC00001.JPG", b"sony-jpg")
    make_file(card / "DCIM" / "100MSDCF" / "DSC00001.ARW", b"sony-raw")
    photos = scan_source(card, reader)
    r2 = next(p for p in photos if p.filename == "R0000002.JPG")
    r1 = [p for p in photos if p.filename.startswith("R0000001")]
    plan = build_plan(card, tmp_path / "t", photos, {r2.key}, {}, deleted_keys={p.key for p in r1})
    plan.include_deleted = True  # the R0000001 pair
    sony = [p.path for p in photos if p.filename.startswith("DSC")]

    breakdown = import_breakdown(plan, shown=set(sony))

    assert [(c.name, c.total, dict(c.counts)) for c in breakdown.cameras] == [
        ("DSC-RX100M7", 1, {"new": 1}),
        ("RICOH GR III", 1, {"deleted": 1}),
    ]
    assert breakdown.cameras[1].saved_to == str(Path("ricoh gr iii", "jpg")) + ", " + str(
        Path("ricoh gr iii", "raw")
    )
    assert (breakdown.pictures, breakdown.files, breakdown.hidden) == (2, 4, 1)
    assert breakdown.statuses == ["new", "deleted"]
    assert dict(breakdown.not_importing) == {"already": 1}


def test_card_title_and_subtitle(tmp_path):
    from photoimporter.core.models import Camera, PhotoFile, PhotoMeta
    from photoimporter.core.planner import CameraGroup, ImportPlan, card_subtitle, card_title

    def shot(name, when):
        return PhotoFile(tmp_path / name, 1, 0, PhotoMeta(capture_time=when))

    ricoh = CameraGroup(Camera("RICOH", "GR III", "Ricoh GR III", "ricoh"), True)
    ricoh.new = [shot("A.JPG", "2026:10:12 09:00:00"), shot("B.JPG", "2026:10:20 09:00:00")]
    ricoh.already = [shot("C.JPG", "2026:10:15 09:00:00")]
    sony = CameraGroup(Camera("SONY", "RX100", "RX100", "sony"), True)
    sony.new = [shot("D.JPG", "2026:10:20 10:00:00")]
    plan = ImportPlan(tmp_path, tmp_path, [sony, ricoh])

    drive = Path(tmp_path.anchor)
    assert card_title(plan, drive) == "Ricoh GR III & RX100 card"  # most photos first
    assert card_title(plan, tmp_path) == "Ricoh GR III & RX100"  # a folder, not a card
    assert card_title(None, None) == "Photo Importer"
    assert card_title(None, tmp_path) == tmp_path.name
    assert card_subtitle(plan) == "4 photos taken Oct 12 – Oct 20 · 3 new since your last import"
    assert card_subtitle(None) == "Insert an SD card, or choose a card or folder."

    ricoh.new, sony.new = [], []
    ricoh.already = [shot("C.JPG", "2025:12:30 09:00:00"), shot("E.JPG", "2026:01:02 09:00:00")]
    assert card_subtitle(plan) == (
        "2 photos taken Dec 30, 2025 – Jan 2, 2026 · nothing new since your last import"
    )
