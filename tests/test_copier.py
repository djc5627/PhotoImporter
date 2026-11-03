from conftest import RICOH, copy_by_hand, make_file

from photoimporter.core.cards import scan_source
from photoimporter.core.copier import execute_plan
from photoimporter.core.indexer import scan_library
from photoimporter.core.models import PhotoMeta
from photoimporter.core.planner import build_plan


def plan_for(db, card, target, reader):
    return build_plan(card, target, scan_source(card, reader), db.existing_keys(), db.cameras())


def test_import_then_replan_finds_nothing_new(db, card, library, reader):
    target = library / "2026.11.02 Hike"
    result = execute_plan(plan_for(db, card, target, reader), db)

    assert result.copied == 3 and not result.failed
    assert (target / "ricoh gr iii" / "raw" / "R0000001.DNG").read_bytes() == b"raw-1-bigger"
    assert not list(target.rglob("*.part"))

    assert plan_for(db, card, target, reader).new_count == 0
    scan_library(db, library, reader)
    assert plan_for(db, card, library / "2026.11.03 Other", reader).new_count == 0


def test_photos_copied_by_hand_are_recognised(db, card, library, reader):
    old = library / "2026.10.01 Old Import" / "ricoh" / "jpg"
    copy_by_hand(card / "DCIM" / "100RICOH" / "R0000001.JPG", old / "R0000001.JPG")
    scan_library(db, library, reader)

    plan = plan_for(db, card, library / "new", reader)

    assert plan.already_count == 1
    assert {p.filename for g in plan.groups for p in g.new} == {"R0000001.DNG", "R0000002.JPG"}


def test_rerun_after_interruption_completes_without_duplicates(db, card, library, reader):
    target = library / "t"
    plan = plan_for(db, card, target, reader)
    first = plan.items[0]
    make_file(first.dest.with_name(first.dest.name + ".part"), b"partial")

    calls = iter([False, True])
    execute_plan(plan, db, should_cancel=lambda: next(calls, True))

    result = execute_plan(plan_for(db, card, target, reader), db)

    assert result.copied == 2 and result.skipped == 0
    assert len([p for p in target.rglob("*") if p.is_file()]) == 3
    assert not list(target.rglob("*.part"))


def test_existing_identical_file_is_skipped_and_indexed(db, card, library, reader):
    target = library / "t"
    plan = plan_for(db, card, target, reader)
    item = plan.items[0]
    copy_by_hand(item.photo.path, item.dest)

    result = execute_plan(plan, db)

    assert result.skipped == 1 and result.copied == 2
    assert item.photo.key in db.existing_keys()


def test_different_photo_with_same_name_is_saved_alongside(db, card, library, reader):
    target = library / "t"
    clash = make_file(target / "ricoh gr iii" / "jpg" / "R0000002.JPG", b"another photo", 1234)

    result = execute_plan(plan_for(db, card, target, reader), db)

    assert clash.read_bytes() == b"another photo"
    assert [p.name for p in result.renamed] == ["R0000002_1.JPG"]
    assert plan_for(db, card, target, reader).new_count == 0


def test_counter_reset_photo_is_imported(db, card, library, reader):
    execute_plan(plan_for(db, card, library / "first", reader), db)
    reader.metas["r0000002.jpg"] = PhotoMeta(**RICOH, capture_time="2027:01:01 08:00:00")

    plan = plan_for(db, card, library / "second", reader)

    assert [p.filename for g in plan.groups for p in g.new] == ["R0000002.JPG"]
