from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

ReportProgress = Callable[[str, int, int], None]


class WorkerSignals(QObject):
    progress = Signal(str, int, int)
    finished = Signal(object)
    failed = Signal(str)


class BackgroundCall(QRunnable):
    """Runs `func()` on the thread pool without marking the window busy.

    Emits `finished` with the result, or `failed` with the error message.
    """

    def __init__(self, func: Callable[[], object]):
        super().__init__()
        self.func = func
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.func()
        except Exception as exc:
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.finished.emit(result)


class Worker(QRunnable):
    """Runs `task(report_progress)` on the thread pool; results come back as signals."""

    def __init__(self, task: Callable[[ReportProgress], object]):
        super().__init__()
        self.task = task
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.task(self.signals.progress.emit)
        except Exception as exc:
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.finished.emit(result)
