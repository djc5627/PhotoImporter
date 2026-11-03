import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from photoimporter.core.db import Database  # noqa: E402
from conftest import copy_by_hand  # noqa: E402
from photoimporter.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path, library, reader, monkeypatch):
    db_path = tmp_path / "ui.db"
    db = Database(db_path)
    db.set_setting("photos_root", str(library))
    db.close()
    win = MainWindow(db_path, reader_factory=lambda: reader)
    qtbot.addWidget(win)
    win.errors, win.notices = [], []
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
