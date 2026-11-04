import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import copy_by_hand  # noqa: E402

from photoimporter.core.db import Database  # noqa: E402
from photoimporter.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path, library, reader, monkeypatch):
    db_path = tmp_path / "ui.db"
    db = Database(db_path)
    db.set_setting("photos_root", str(library))
    db.close()
    win = MainWindow(
        db_path, reader_factory=lambda: reader, card_detector=lambda: win.cards, card_poll_ms=50
    )
    qtbot.addWidget(win)
    win.cards = []
    win.errors, win.notices, win.asked_cameras = [], [], []

    def ask_camera(group):
        win.asked_cameras.append(group.camera)
        return win.camera_answers.pop(0) if win.camera_answers else group.camera

    win.camera_answers = []
    monkeypatch.setattr(win, "_ask_camera", ask_camera)
    monkeypatch.setattr(win, "_confirm", lambda text: True)
    monkeypatch.setattr(win, "_notify", win.notices.append)
    monkeypatch.setattr(win, "_show_error", win.errors.append)
    return win


def test_find_then_import_into_new_folder(qtbot, window, card, library):
    window.description_edit.setText("Halloween Hike")
    window.source_edit.setText(str(card))
    folder = library / f"{date.today():%Y.%m.%d} Halloween Hike"
    assert window.target_preview.text() == str(folder)

    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    row = window.plan_tree.topLevelItem(0)
    assert [row.text(i) for i in range(5)] == [
        "RICOH GR III (new camera)",
        f"ricoh gr iii{os.sep}jpg, ricoh gr iii{os.sep}raw",
        "2",
        "1",
        "0",
    ]
    assert window.import_button.isEnabled()

    with qtbot.waitSignal(window.import_done, timeout=10_000):
        window.import_button.click()
    assert (folder / "ricoh gr iii" / "raw" / "R0000001.DNG").is_file()
    assert window.notices == ["Copied 3 photos."]
    assert not window.import_button.isEnabled()

    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    assert window.status_label.text() == "Nothing new: all 3 photos already imported."
    assert not window.import_button.isEnabled()


def test_import_into_existing_folder(qtbot, window, card, library):
    existing = library / "2026.11.02 Hike"
    existing.mkdir()
    window.existing_radio.setChecked(True)
    window.existing_edit.setText(str(existing))
    window.source_edit.setText(str(card))

    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    with qtbot.waitSignal(window.import_done, timeout=10_000):
        window.import_button.click()

    assert (existing / "ricoh gr iii" / "jpg" / "R0000002.JPG").is_file()


def test_old_style_folders_are_left_alone(qtbot, window, card, library):
    """Pre-app folders use 'M.D.YYYY Description'. Capture One links to those
    paths, so they must still count as imported and never be renamed or moved."""
    old = library / "11.2.2026 Hike"
    copy_by_hand(card / "DCIM" / "100RICOH" / "R0000001.JPG", old / "R0000001.JPG")
    before = sorted(p.relative_to(library) for p in library.rglob("*"))

    window.existing_radio.setChecked(True)
    window.existing_edit.setText(str(old))
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    assert window.plan_tree.topLevelItem(0).text(3) == "1"  # already imported
    with qtbot.waitSignal(window.import_done, timeout=10_000):
        window.import_button.click()

    after = sorted(p.relative_to(library) for p in library.rglob("*"))
    assert set(before) <= set(after)
    assert [p for p in library.iterdir()] == [old]
    assert (old / "R0000001.JPG").is_file()
    assert (old / "ricoh gr iii" / "jpg" / "R0000002.JPG").is_file()


def test_deleted_photos_are_skipped_until_ticked(qtbot, window, card, library):
    target = library / "2026.11.02 Hike"
    window.existing_radio.setChecked(True)
    window.existing_edit.setText(str(target))
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    with qtbot.waitSignal(window.import_done, timeout=10_000):
        window.import_button.click()
    deleted = target / "ricoh gr iii" / "jpg" / "R0000002.JPG"
    deleted.unlink()

    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    row = window.plan_tree.topLevelItem(0)
    assert [row.text(i) for i in range(2, 8)] == ["0", "0", "2", "1", "0", "0"]
    assert window.status_label.text() == (
        "0 new photos, 2 already imported, 1 recently deleted (skipped)."
    )
    assert not window.import_button.isEnabled()
    assert window.include_recent_deleted_check.isVisibleTo(window)
    assert not window.include_deleted_check.isVisibleTo(window)
    assert not window.include_older_check.isVisibleTo(window)

    window.include_recent_deleted_check.setChecked(True)
    assert window.import_button.isEnabled()
    assert window.plan_tree.topLevelItem(0).text(1) == f"ricoh gr iii{os.sep}jpg"
    with qtbot.waitSignal(window.import_done, timeout=10_000):
        window.import_button.click()
    assert deleted.is_file()
    assert not window.include_recent_deleted_check.isChecked()


def test_import_requires_a_target(qtbot, window, card):
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()

    window.import_button.click()

    assert window.errors == ["Enter a description for the new folder, or choose an existing one."]


def test_missing_source_is_reported(window):
    window.source_edit.setText("")
    window.find_button.click()
    assert window.errors == ["Choose an SD card or folder to import from."]


def test_worker_errors_are_shown(qtbot, window, card):
    def broken_reader():
        raise RuntimeError("ExifTool exploded")

    window.reader_factory = broken_reader
    window.source_edit.setText(str(card))

    with qtbot.waitSignal(window.task_failed, timeout=10_000):
        window.find_button.click()

    assert window.errors == ["ExifTool exploded"]
    assert window.find_button.isEnabled()


def test_inserting_a_card_finds_new_photos(qtbot, window, card):
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.cards = [card]
    assert window.source_edit.text() == str(card)
    assert window.plan.new_count == 3

    window.cards = []
    qtbot.waitUntil(lambda: window.plan is None, timeout=5_000)
    assert window.status_label.text() == f"Card removed: {card}."


def test_card_inserted_while_busy_is_checked_afterwards(qtbot, window, card, tmp_path):
    other = tmp_path / "other"
    (other / "DCIM").mkdir(parents=True)
    window.source_edit.setText(str(card))
    window.find_button.click()
    window.on_card_inserted(other)  # arrives while the first search is running
    assert window._pending_card == other
    assert window.source_edit.text() == str(card)

    qtbot.waitUntil(lambda: window.plan is not None and window.plan.source == other, timeout=10_000)
    assert window.source_edit.text() == str(other)


def test_new_camera_is_named_before_import(qtbot, window, card, library):
    from photoimporter.core.models import Camera

    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    answer = Camera("RICOH IMAGING COMPANY, LTD.", "RICOH GR III", "Ricoh", "ricoh", "JPG", "DNG")
    window.camera_answers = [answer]
    window.description_edit.setText("Walk")

    with qtbot.waitSignal(window.import_done, timeout=10_000):
        window.import_button.click()

    assert [c.model for c in window.asked_cameras] == ["RICOH GR III"]
    folder = window.target_dir()
    assert (folder / "ricoh" / "DNG" / "R0000001.DNG").is_file()
    assert window.db.cameras()[("RICOH IMAGING COMPANY, LTD.", "RICOH GR III")] == answer


def test_cancelling_camera_dialog_cancels_import(qtbot, window, card, monkeypatch):
    monkeypatch.setattr(window, "_ask_camera", lambda group: None)
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    window.description_edit.setText("Walk")

    window.import_button.click()

    assert window.status_label.text() == "Import cancelled."
    assert window.db.cameras() == {}
    assert not window.target_dir().exists()


def test_new_camera_gets_folders_it_already_uses_in_library(qtbot, window, card, library):
    old = library / "10.1.2025 Trip" / "gr3" / "JPEG"
    copy_by_hand(card / "DCIM" / "100RICOH" / "R0000001.JPG", old / "R0000001.JPG")
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()

    group = window.plan.groups[0]
    assert group.library_match
    assert (group.camera.folder_name, group.camera.jpg_dir) == ("gr3", "JPEG")
    assert window.camera_folders == ["gr3"]
    assert window.plan_tree.topLevelItem(0).text(1).startswith(f"gr3{os.sep}")


def test_camera_dialog_cleans_folder_names(qtbot):
    from photoimporter.core.models import Camera
    from photoimporter.ui.camera_dialog import CameraDialog

    dialog = CameraDialog(Camera.default_for("SONY", "ILCE-7RM5"), 4, False, ["ricoh"])
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    assert dialog.camera().folder_name == "ilce-7rm5"

    dialog.folder_combo.setCurrentText("  ")
    assert not ok.isEnabled()
    dialog.folder_combo.setCurrentText("sony: a7r v")
    dialog.nickname_edit.setText("a7R V")
    assert ok.isEnabled()
    assert (dialog.camera().nickname, dialog.camera().folder_name) == ("a7R V", "sony_ a7r v")
