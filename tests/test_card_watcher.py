import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from photoimporter.ui.card_watcher import CardWatcher  # noqa: E402


def test_reports_insertions_and_removals(qtbot):
    cards = [Path("E:/")]
    watcher = CardWatcher(lambda: cards, interval_ms=10_000)
    inserted, removed = [], []
    watcher.inserted.connect(inserted.append)
    watcher.removed.connect(removed.append)

    watcher.poll()
    watcher.poll()
    cards[:] = [Path("F:/")]
    watcher.poll()

    assert inserted == [Path("E:/"), Path("F:/")]
    assert removed == [Path("E:/")]


def test_drive_errors_are_ignored(qtbot):
    def broken():
        raise OSError("device not ready")

    watcher = CardWatcher(broken)
    watcher.poll()
    assert watcher.known == set()
