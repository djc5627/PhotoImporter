from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.cards import detect_cards


class CardWatcher(QObject):
    """Polls for SD cards and reports insertions and removals.

    Cards already present when the watcher starts are reported as inserted.
    """

    inserted = Signal(object)
    removed = Signal(object)

    def __init__(
        self,
        detector: Callable[[], list[Path]] = detect_cards,
        interval_ms: int = 2000,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.detector = detector
        self.known: set[Path] = set()
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.poll)

    def start(self) -> None:
        QTimer.singleShot(0, self.poll)
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def poll(self) -> None:
        try:
            current = set(self.detector())
        except OSError:
            return
        gone, added = self.known - current, current - self.known
        self.known = current
        for card in sorted(gone):
            self.removed.emit(card)
        for card in sorted(added):
            self.inserted.emit(card)
