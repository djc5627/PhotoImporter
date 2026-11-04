import os
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import copy_by_hand  # noqa: E402
from PySide6.QtCore import QBuffer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from photoimporter.core.db import Database  # noqa: E402
from photoimporter.core.thumbnails import Thumbnail  # noqa: E402
from photoimporter.ui.main_window import MainWindow  # noqa: E402


class FakeThumbnails:
    """A 4x3 orange thumbnail for JPGs, none for RAWs."""

    calls: list[list[Path]] = []

    def extract(self, paths):
        FakeThumbnails.calls.append(list(paths))
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("orange"))
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "JPG")
        data = bytes(buffer.data())
        return {p: Thumbnail(data if p.suffix == ".JPG" else None) for p in paths}


@pytest.fixture
def window(qtbot, tmp_path, library, reader, monkeypatch):
    db_path = tmp_path / "ui.db"
    db = Database(db_path)
    db.set_setting("photos_root", str(library))
    db.close()
    win = MainWindow(
        db_path,
        reader_factory=lambda: reader,
        card_detector=lambda: win.cards,
        card_poll_ms=50,
        thumbnail_factory=FakeThumbnails,
        update_checker=None,
        recycler_factory=lambda: lambda paths: win.recycle(paths),
        deleted_staging=tmp_path / "deleted",
    )
    qtbot.addWidget(win)
    win.cards = []
    win.errors, win.notices, win.asked_cameras = [], [], []

    def ask_camera(group):
        win.asked_cameras.append(group.camera)
        return win.camera_answers.pop(0) if win.camera_answers else group.camera

    win.camera_answers = []
    win.recycled = []

    def recycle(paths):  # stands in for the Windows Recycle Bin
        win.recycled.extend(p.name for p in paths)
        for path in paths:
            path.unlink()
        return set()

    win.recycle = recycle
    monkeypatch.setattr(win, "_ask_camera", ask_camera)
    win.confirmations = []
    monkeypatch.setattr(win, "_confirm", lambda text: win.confirmations.append(text) or True)
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

    window.include_recent_deleted_check.click()
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


def test_thumbnail_grid_shows_raw_jpg_pairs_once(qtbot, window, card):
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.grid.thumbnails_loaded, timeout=10_000):
        window.find_button.click()

    grid = window.grid
    assert [(s.name, s.badge) for s in grid.shots()] == [("R0000002", ""), ("R0000001", "RAW+JPG")]
    assert grid.view_combo.currentText() == "All on card (3)"
    assert grid.count_label.text() == "2 pictures, 2 selected"
    assert window.import_button.text() == "Import 2 photos (3 files)"
    image = grid.cache[card / "DCIM" / "100RICOH" / "R0000001.JPG"]
    assert (image.width(), image.height()) == (160, 120)  # scaled up to the tile, 4:3 kept


def find_with_sony_and_one_imported(qtbot, window, card, library):
    """Card: DSC00001 (Sony, 11:00, new), R0000002 (10:05, already imported),
    R0000001 JPG+DNG (10:00, older than the library's newest Ricoh: probably deleted)."""
    from conftest import make_file

    make_file(card / "DCIM" / "100MSDCF" / "DSC00001.JPG", b"sony-jpg")
    copy_by_hand(card / "DCIM" / "100RICOH" / "R0000002.JPG", library / "x" / "R0000002.JPG")
    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    return window.grid


def view(grid, label):
    combo = grid.view_combo
    combo.setCurrentIndex(
        next(i for i in range(combo.count()) if combo.itemText(i).startswith(label))
    )


def chosen(grid):
    from photoimporter.ui.thumbnail_grid import CHOSEN_ROLE

    return {
        grid.list.item(i).data(Qt.ItemDataRole.UserRole).name: grid.list.item(i).data(CHOSEN_ROLE)
        for i in range(grid.list.count())
    }


def mouse_click(qtbot, grid, name, modifier=None):
    rect = grid.list.visualItemRect(grid.item_for(name))
    qtbot.mouseClick(
        grid.list.viewport(),
        Qt.MouseButton.LeftButton,
        modifier or Qt.KeyboardModifier.NoModifier,
        rect.center(),
    )


def test_all_on_card_newest_first_with_statuses(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)

    assert [s.name for s in grid.shots()] == ["DSC00001", "R0000002", "R0000001"]
    assert chosen(grid) == {"DSC00001": "on", "R0000002": "off", "R0000001": "off"}
    assert "R0000002.JPG (already imported)" in grid.item_for("R0000002").toolTip()

    view(grid, "Probably deleted")
    assert [s.name for s in grid.shots()] == ["R0000001"]
    view(grid, "Selected for import")
    assert [s.name for s in grid.shots()] == ["DSC00001"]

    ricoh = next(
        window.plan_tree.topLevelItem(i)
        for i in range(window.plan_tree.topLevelItemCount())
        if window.plan_tree.topLevelItem(i).text(0).startswith("RICOH")
    )
    view(grid, "All on card")
    ricoh.setSelected(True)
    assert [s.name for s in grid.shots()] == ["R0000002", "R0000001"]


def test_clicking_toggles_photos(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)

    mouse_click(qtbot, grid, "R0000001")
    assert window.plan.include_older  # both files of the pair
    assert window.include_older_check.checkState() == Qt.CheckState.Checked
    assert window.import_button.text() == "Import 2 photos (3 files)"

    mouse_click(qtbot, grid, "DSC00001")
    assert chosen(grid)["DSC00001"] == "off"
    assert window.status_label.text() == (
        "1 new photo (0 selected), 1 already imported, 2 probably deleted earlier (included)."
    )
    assert window.import_button.text() == "Import 1 photo (2 files)"

    grid.select_none_button.click()
    assert set(chosen(grid).values()) == {"off"}
    assert not window.import_button.isEnabled()
    grid.select_all_button.click()
    assert set(chosen(grid).values()) == {"on"}
    # The already-imported photo is selected (e.g. to delete it) but not imported again.
    assert window.import_button.text() == "Import 2 photos (3 files)"
    assert "to import again" not in window.status_label.text()


def test_shift_click_selects_a_range(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)
    grid.select_none_button.click()

    mouse_click(qtbot, grid, "R0000001")  # anchor (bottom)
    mouse_click(qtbot, grid, "DSC00001", Qt.KeyboardModifier.ShiftModifier)  # up to the top

    assert chosen(grid) == {"DSC00001": "on", "R0000002": "on", "R0000001": "on"}


def test_keyboard_and_double_click(qtbot, window, card, library, monkeypatch):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)
    opened = []
    monkeypatch.setattr(grid, "_open", lambda item: opened.append(item.text()))

    grid.list.setCurrentItem(grid.item_for("R0000002"))
    qtbot.keyClick(grid.list, Qt.Key.Key_Space)
    assert chosen(grid)["R0000002"] == "on"
    qtbot.keyClick(grid.list, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert set(chosen(grid).values()) == {"on"}

    # A double-click opens the photo and leaves its selection as it was.
    item, button = grid.item_for("DSC00001"), Qt.MouseButton.LeftButton
    pos = grid.list.visualItemRect(item).center()
    qtbot.mousePress(grid.list.viewport(), button, pos=pos)
    qtbot.mouseRelease(grid.list.viewport(), button, pos=pos)
    qtbot.mouseDClick(grid.list.viewport(), button, pos=pos)
    qtbot.mouseRelease(grid.list.viewport(), button, pos=pos)
    assert opened == ["DSC00001"]
    assert chosen(grid)["DSC00001"] == "on"


def test_include_tick_shows_partial_and_selects_the_whole_group(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)
    window.include_older_check.click()
    assert chosen(grid)["R0000001"] == "on"

    mouse_click(qtbot, grid, "R0000001")
    assert window.include_older_check.checkState() == Qt.CheckState.Unchecked
    window.plan.select([window.plan.photos("older")[0]])  # one file of the pair
    grid.refresh_checks()
    window._refresh_selection_view()
    assert chosen(grid)["R0000001"] == "part"
    assert window.include_older_check.checkState() == Qt.CheckState.PartiallyChecked
    assert "2 probably deleted earlier (1 included)" in window.status_label.text()


def test_reimporting_needs_permission(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)
    assert window.allow_reimport_check.isVisibleTo(window)
    assert not window.include_already_check.isVisibleTo(window)
    mouse_click(qtbot, grid, "R0000002")
    assert window.import_button.text() == "Import 1 photo"  # just DSC00001

    window.allow_reimport_check.click()
    assert window.include_already_check.isVisibleTo(window)
    assert window.include_already_check.checkState() == Qt.CheckState.Checked
    assert window.import_button.text() == "Import 2 photos"
    assert "1 already imported (1 to import again)" in window.status_label.text()

    window.allow_reimport_check.click()
    assert window.import_button.text() == "Import 1 photo"
    assert chosen(grid)["R0000002"] == "on"  # still selected, e.g. for deleting


def test_delete_selected_photos_shown_from_the_card(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)
    dcim = card / "DCIM"
    view(grid, "Probably deleted")
    grid.select_all_button.click()  # R0000001 pair; DSC00001 is selected too but not shown

    grid.delete_button.click()
    qtbot.waitUntil(lambda: not window._busy, timeout=10_000)

    assert "Delete 1 photo (2 files) from the SD card?" in window.confirmations[-1]
    assert "Recycle Bin" in window.confirmations[-1]
    assert sorted(window.recycled) == ["R0000001.DNG", "R0000001.JPG"]
    assert not (dcim / "100RICOH" / "R0000001.JPG").exists()
    assert (dcim / "100RICOH" / "R0000002.JPG").exists()
    assert (dcim / "100MSDCF" / "DSC00001.JPG").exists()
    assert window.status_label.text() == "Deleted 1 photo from the card."
    assert window.plan.older_count == 0
    view(grid, "All on card")
    assert [s.name for s in grid.shots()] == ["DSC00001", "R0000002"]


def test_delete_is_disabled_without_a_selection(qtbot, window, card, library):
    grid = find_with_sony_and_one_imported(qtbot, window, card, library)
    assert grid.delete_button.isEnabled()
    grid.select_none_button.click()
    assert not grid.delete_button.isEnabled()
    qtbot.keyClick(grid.list, Qt.Key.Key_Delete)
    assert window.confirmations == []


def test_settings_dialog_saves_general_settings_and_cameras(qtbot, window, library):
    from photoimporter.core.config import format_date
    from photoimporter.core.models import Camera
    from photoimporter.ui.settings_dialog import SettingsDialog

    db = window.db
    db.save_camera(Camera("RICOH", "GR III", "Ricoh", "ricoh"))
    db.save_camera(Camera("Canon", "EOS 6D Mark II", "6D", "canon 6d"))
    dialog = SettingsDialog(db)
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)

    dialog.date_combo.setCurrentText("YYYY.MM")
    assert not ok.isEnabled()
    dialog.date_combo.setCurrentText("M.D.YYYY")
    assert ok.isEnabled()
    today = format_date(date.today(), "M.D.YYYY")
    assert dialog.date_preview.text().endswith(f"{today} Description")
    dialog.find_on_insert_check.setChecked(False)

    table = dialog.camera_table
    assert [table.item(r, 1).text() for r in range(table.rowCount())] == ["6D", "Ricoh"]
    table.item(1, 2).setText("  ricoh gr3 ")
    table.item(1, 3).setText("")
    table.selectRow(0)
    dialog.forget_button.click()
    dialog.accept()

    assert db.get_setting("date_format") == "M.D.YYYY"
    assert db.get_setting("find_on_insert") == "0"
    assert db.cameras() == {
        ("RICOH", "GR III"): Camera("RICOH", "GR III", "Ricoh", "ricoh gr3", "", "raw")
    }


def test_settings_changes_apply_to_the_open_plan(qtbot, window, card, monkeypatch):
    from photoimporter.core.models import Camera

    window.source_edit.setText(str(card))
    with qtbot.waitSignal(window.plan_ready, timeout=10_000):
        window.find_button.click()
    assert window.plan_tree.topLevelItem(0).text(0) == "RICOH GR III (new camera)"

    def edit_settings():
        camera = window.plan.groups[0].camera
        window.db.save_camera(Camera(camera.make, camera.model, "GR", "gr"))
        window.db.set_setting("date_format", "YYYY-MM-DD")
        return True

    monkeypatch.setattr(window, "_exec_settings", edit_settings)
    window.description_edit.setText("Walk")
    window.open_settings()

    assert window.plan_tree.topLevelItem(0).text(0) == "GR"
    assert window.plan_tree.topLevelItem(0).text(1).startswith(f"gr{os.sep}")
    assert window.target_preview.text().endswith(f"{date.today():%Y-%m-%d} Walk")


def test_card_insert_can_just_fill_in_the_source(qtbot, window, card):
    window.db.set_setting("find_on_insert", "0")
    window.cards = [card]
    qtbot.waitUntil(lambda: window.source_edit.text() == str(card), timeout=5_000)
    assert window.plan is None
    assert window.status_label.text() == f"Card inserted: {card}. Click Find new photos."


def make_window(qtbot, tmp_path, update_checker):
    win = MainWindow(
        tmp_path / "ui.db",
        card_detector=lambda: [],
        thumbnail_factory=FakeThumbnails,
        update_checker=update_checker,
    )
    qtbot.addWidget(win)
    return win


def test_update_bar_offers_a_newer_release(qtbot, tmp_path, monkeypatch):
    from photoimporter.core.updates import Release

    opened = []
    monkeypatch.setattr("PySide6.QtGui.QDesktopServices.openUrl", lambda url: opened.append(url))
    release = Release("9.0.0", "https://github.com/x/y/releases/tag/v9.0.0", None)
    win = make_window(qtbot, tmp_path, lambda: release)
    qtbot.waitUntil(lambda: win.update_bar.isVisibleTo(win), timeout=5_000)
    assert "Photo Importer 9.0.0" in win.update_label.text()

    win.update_download_button.click()
    assert opened[0].toString() == release.page_url

    win.update_skip_button.click()
    assert not win.update_bar.isVisibleTo(win)
    assert win.db.get_setting("skipped_version") == "9.0.0"
    win.close()

    again = make_window(qtbot, tmp_path, lambda: release)
    with qtbot.waitSignal(again.update_checked, timeout=5_000):
        pass
    assert not again.update_bar.isVisibleTo(again)  # skipped version stays quiet


def test_update_check_failures_and_opt_out_are_quiet(qtbot, tmp_path):
    def offline():
        raise OSError("no network")

    win = make_window(qtbot, tmp_path, offline)
    with qtbot.waitSignal(win.update_checked, timeout=5_000) as signal:
        pass
    assert signal.args == [None]
    assert not win.update_bar.isVisibleTo(win)
    win.db.set_setting("check_updates", "0")
    win.close()

    calls = []
    make_window(qtbot, tmp_path, lambda: calls.append(1))
    qtbot.wait(100)
    assert calls == []
