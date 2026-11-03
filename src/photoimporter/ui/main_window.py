from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.cameras import LibraryLayout, apply_camera_suggestions
from ..core.cards import detect_cards, scan_source
from ..core.config import new_import_folder, photos_root
from ..core.copier import CopyResult, execute_plan
from ..core.db import Database
from ..core.exif import ExifToolReader, MetadataReader
from ..core.indexer import ScanResult, scan_library
from ..core.models import Camera
from ..core.planner import CameraGroup, ImportPlan, build_plan
from .camera_dialog import CameraDialog
from .card_watcher import CardWatcher
from .workers import ReportProgress, Worker


def _photos(n: int) -> str:
    return f"{n} photo" if n == 1 else f"{n} photos"


class MainWindow(QMainWindow):
    plan_ready = Signal(object)
    import_done = Signal(object)
    task_failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        reader_factory: Callable[[], MetadataReader] = ExifToolReader,
        card_detector: Callable[[], list[Path]] = detect_cards,
        card_poll_ms: int = 2000,
    ):
        super().__init__()
        self.db_path = db_path
        self.reader_factory = reader_factory
        self.card_detector = card_detector
        self.db = Database(db_path)
        self.plan: ImportPlan | None = None
        self.camera_folders: list[str] = []
        self._worker: Worker | None = None
        self._cancel = threading.Event()
        self._busy = False
        self._pending_card: Path | None = None

        self.setWindowTitle("Photo Importer")
        self.resize(860, 620)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_library_box())
        layout.addWidget(self._build_target_box())
        layout.addWidget(self._build_source_box())
        layout.addWidget(self._build_plan_box(), stretch=1)
        layout.addLayout(self._build_footer())
        self.setCentralWidget(central)

        self._refresh_library_label()
        self._refresh_target_preview()
        self.status_label.setText("Insert an SD card, or browse to a card or folder.")
        self.card_watcher = CardWatcher(card_detector, card_poll_ms, self)
        self.card_watcher.inserted.connect(self.on_card_inserted)
        self.card_watcher.removed.connect(self.on_card_removed)
        self.card_watcher.start()

    # Layout

    def _build_library_box(self) -> QGroupBox:
        box = QGroupBox("Photo library")
        row = QHBoxLayout(box)
        self.library_label = QLabel()
        self.change_root_button = QPushButton("Change…")
        self.change_root_button.clicked.connect(self.choose_photos_root)
        self.rescan_button = QPushButton("Rescan library")
        self.rescan_button.clicked.connect(self.rescan_library)
        row.addWidget(self.library_label, stretch=1)
        row.addWidget(self.change_root_button)
        row.addWidget(self.rescan_button)
        return box

    def _build_target_box(self) -> QGroupBox:
        box = QGroupBox("Import into")
        grid = QGridLayout(box)
        self.new_radio = QRadioButton("New folder")
        self.existing_radio = QRadioButton("Existing folder")
        self.new_radio.setChecked(True)
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Description, e.g. Halloween Hike")
        self.target_preview = QLabel()
        self.target_preview.setStyleSheet("color: gray")
        self.existing_edit = QLineEdit()
        self.existing_edit.setPlaceholderText("Choose a folder in your library")
        self.browse_target_button = QPushButton("Browse…")
        self.browse_target_button.clicked.connect(self.choose_existing_target)

        grid.addWidget(self.new_radio, 0, 0)
        grid.addWidget(self.description_edit, 0, 1, 1, 2)
        grid.addWidget(self.target_preview, 1, 1, 1, 2)
        grid.addWidget(self.existing_radio, 2, 0)
        grid.addWidget(self.existing_edit, 2, 1)
        grid.addWidget(self.browse_target_button, 2, 2)
        grid.setColumnStretch(1, 1)

        for signal in (
            self.new_radio.toggled,
            self.description_edit.textChanged,
            self.existing_edit.textChanged,
        ):
            signal.connect(self._refresh_target_preview)
        return box

    def _build_source_box(self) -> QGroupBox:
        box = QGroupBox("Import from")
        row = QHBoxLayout(box)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("SD card or folder")
        self.browse_source_button = QPushButton("Browse…")
        self.browse_source_button.clicked.connect(self.choose_source)
        self.detect_button = QPushButton("Detect card")
        self.detect_button.clicked.connect(self.detect_card)
        self.find_button = QPushButton("Find new photos")
        self.find_button.setDefault(True)
        self.find_button.clicked.connect(self.find_new_photos)
        row.addWidget(self.source_edit, stretch=1)
        row.addWidget(self.browse_source_button)
        row.addWidget(self.detect_button)
        row.addWidget(self.find_button)
        return box

    def _build_plan_box(self) -> QGroupBox:
        box = QGroupBox("New photos")
        layout = QVBoxLayout(box)
        self.plan_tree = QTreeWidget()
        self.plan_tree.setHeaderLabels(
            [
                "Camera",
                "Saved to",
                "New JPG",
                "New RAW",
                "Already imported",
                "Deleted",
                "Probably deleted",
            ]
        )
        header_item = self.plan_tree.headerItem()
        header_item.setToolTip(5, "Imported before, then deleted from your library")
        header_item.setToolTip(
            6, "Older than the newest library photo from this camera, so most likely deleted"
        )
        self.plan_tree.setRootIsDecorated(False)
        header = self.plan_tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.plan_tree)

        self.include_deleted_check = QCheckBox()
        self.include_deleted_check.setToolTip(
            "Photos that were imported before and later deleted from your library,\n"
            "for example during a cleanup in Capture One. Skipped unless ticked."
        )
        self.include_older_check = QCheckBox()
        self.include_older_check.setToolTip(
            "Photos that are not in your library but are older than the newest photo\n"
            "already there from the same camera, so they were most likely imported and\n"
            "deleted before the app kept a history. Skipped unless ticked."
        )
        for check in (self.include_deleted_check, self.include_older_check):
            check.toggled.connect(self._on_include_toggled)
            layout.addWidget(check)
        self._refresh_include_checks()
        return box

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.status_label = QLabel("Ready.")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel.set)
        self.import_button = QPushButton("Import")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.start_import)
        row.addWidget(self.status_label, stretch=1)
        row.addWidget(self.progress_bar, stretch=1)
        row.addWidget(self.cancel_button)
        row.addWidget(self.import_button)
        return row

    # Library

    def _refresh_library_label(self) -> None:
        self.library_label.setText(
            f"{photos_root(self.db)}   ({self.db.file_count():,} photos indexed)"
        )

    def choose_photos_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Photo library folder", str(photos_root(self.db))
        )
        if folder:
            self.db.set_setting("photos_root", str(Path(folder)))
            self._refresh_library_label()
            self._refresh_target_preview()

    def rescan_library(self) -> None:
        root = photos_root(self.db)
        db_path, reader_factory = self.db_path, self.reader_factory

        def task(report: ReportProgress) -> ScanResult:
            db = Database(db_path)
            try:
                return scan_library(
                    db, root, reader_factory(), lambda d, t: report("Indexing library", d, t)
                )
            finally:
                db.close()

        self._run("Indexing library", task, self._on_rescan_done)

    def _on_rescan_done(self, result: ScanResult) -> None:
        self._refresh_library_label()
        self.status_label.setText(
            f"Library updated: {result.added} added, {result.updated} changed, "
            f"{result.removed} removed."
        )

    # Target and source

    def target_dir(self) -> Path | None:
        if self.new_radio.isChecked():
            description = self.description_edit.text().strip()
            if not description:
                return None
            return new_import_folder(photos_root(self.db), description, date.today())
        text = self.existing_edit.text().strip()
        return Path(text) if text else None

    def _refresh_target_preview(self) -> None:
        is_new = self.new_radio.isChecked()
        self.description_edit.setEnabled(is_new)
        self.existing_edit.setEnabled(not is_new)
        self.browse_target_button.setEnabled(not is_new)
        target = self.target_dir() if is_new else None
        self.target_preview.setText(str(target) if target else "")

    def choose_existing_target(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import folder", str(photos_root(self.db)))
        if folder:
            self.existing_edit.setText(str(Path(folder)))

    def choose_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "SD card or folder", self.source_edit.text()
        )
        if folder:
            self.source_edit.setText(str(Path(folder)))

    def detect_card(self) -> None:
        cards = self.card_detector()
        if cards:
            self.source_edit.setText(str(cards[0]))
            self.status_label.setText(f"Card detected: {', '.join(map(str, cards))}")
        else:
            self.status_label.setText("No card detected. Browse to a card or folder.")

    def on_card_inserted(self, card: Path) -> None:
        """A card was inserted (or was already in when the app started): look at it."""
        if self._busy:
            self._pending_card = card
            self.status_label.setText(f"Card inserted: {card}. Checking it when this finishes…")
            return
        self.source_edit.setText(str(card))
        self.find_new_photos()

    def on_card_removed(self, card: Path) -> None:
        if self._pending_card == card:
            self._pending_card = None
        if self._busy or Path(self.source_edit.text().strip() or ".") != card:
            return
        self._set_plan(None)
        self.status_label.setText(f"Card removed: {card}.")

    # Planning

    def find_new_photos(self) -> None:
        source = Path(self.source_edit.text().strip())
        if not self.source_edit.text().strip() or not source.is_dir():
            self._show_error("Choose an SD card or folder to import from.")
            return
        root = photos_root(self.db)
        if not root.is_dir():
            self._show_error(f"Photo library folder not found: {root}")
            return
        db_path, reader_factory = self.db_path, self.reader_factory

        def task(report: ReportProgress) -> ImportPlan:
            db = Database(db_path)
            try:
                reader = reader_factory()
                scan_library(db, root, reader, lambda d, t: report("Indexing library", d, t))
                photos = scan_source(source, reader, lambda d, t: report("Reading card", d, t))
                # The target is filled in at import time, so it can still be changed.
                plan = build_plan(
                    source,
                    root,
                    photos,
                    db.existing_keys(),
                    db.cameras(),
                    db.deleted_keys(),
                    db.newest_capture_by_model(),
                )
                layout = LibraryLayout.from_db(db, root)
                apply_camera_suggestions(plan, layout)
                return plan, layout.camera_folders
            finally:
                db.close()

        self._set_plan(None)
        self._run("Looking for new photos", task, self._on_plan_ready)

    def _on_plan_ready(self, result: tuple[ImportPlan, list[str]]) -> None:
        plan, self.camera_folders = result
        self._set_plan(plan)
        self._refresh_library_label()
        self.plan_ready.emit(plan)

    def _set_plan(self, plan: ImportPlan | None) -> None:
        """Show a fresh plan. Deleted photos always start out skipped."""
        self.plan = plan
        for check in (self.include_deleted_check, self.include_older_check):
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)
        self._refresh_plan_view()

    def _on_include_toggled(self) -> None:
        if self.plan is not None:
            self.plan.include_deleted = self.include_deleted_check.isChecked()
            self.plan.include_older = self.include_older_check.isChecked()
        self._refresh_plan_view()

    def _refresh_plan_view(self) -> None:
        plan = self.plan
        self.plan_tree.clear()
        self._refresh_include_checks()
        if plan is None:
            self.import_button.setEnabled(False)
            self.import_button.setText("Import")
            return
        for group in plan.groups:
            self.plan_tree.addTopLevelItem(self._plan_row(plan, group))
        self.import_button.setEnabled(plan.copy_count > 0)
        self.import_button.setText(f"Import {plan.copy_count}" if plan.copy_count else "Import")
        self.status_label.setText(plan.summary())

    def _refresh_include_checks(self) -> None:
        plan = self.plan
        deleted = plan.deleted_count if plan else 0
        older = plan.older_count if plan else 0
        self.include_deleted_check.setText(
            f"Include {_photos(deleted)} deleted since import (imported before, then deleted)"
        )
        self.include_older_check.setText(
            f"Include {_photos(older)} probably deleted earlier "
            "(older than your newest library photo from that camera)"
        )
        self.include_deleted_check.setVisible(deleted > 0)
        self.include_older_check.setVisible(older > 0)

    @staticmethod
    def _plan_row(plan: ImportPlan, group: CameraGroup) -> QTreeWidgetItem:
        cam = group.camera
        counts = group.new_by_kind()
        name = cam.nickname if group.registered else f"{cam.nickname} (new camera)"
        kinds = sorted({p.kind for p in plan.to_copy(group)})
        folders = ", ".join(str(Path(cam.folder_name, cam.subdir_for(k))) for k in kinds) or "—"
        return QTreeWidgetItem(
            [
                name,
                folders,
                str(counts["jpg"]),
                str(counts["raw"]),
                str(len(group.already)),
                str(len(group.deleted)),
                str(len(group.older)),
            ]
        )

    # Importing

    def start_import(self) -> None:
        plan = self.plan
        target = self.target_dir()
        if plan is None or plan.copy_count == 0:
            return
        if target is None:
            self._show_error("Enter a description for the new folder, or choose an existing one.")
            return
        for group in plan.groups:
            if group.registered or not plan.to_copy(group):
                continue
            camera = self._ask_camera(group)
            if camera is None:
                self.status_label.setText("Import cancelled.")
                return
            self.db.save_camera(camera)
            group.camera, group.registered = camera, True
            self._refresh_plan_view()
        plan.target_dir = target
        if not self._confirm(f"Copy {plan.copy_count} photos into\n{target}?"):
            return
        db_path, cancel = self.db_path, self._cancel
        cancel.clear()

        def task(report: ReportProgress) -> CopyResult:
            db = Database(db_path)
            try:
                for camera in plan.unregistered:
                    db.save_camera(camera)
                return execute_plan(
                    plan, db, lambda d, t: report("Copying", d, t), should_cancel=cancel.is_set
                )
            finally:
                db.close()

        self.cancel_button.setVisible(True)
        self._run("Copying", task, self._on_import_done)

    def _on_import_done(self, result: CopyResult) -> None:
        self.cancel_button.setVisible(False)
        self._set_plan(None)
        self._refresh_library_label()
        message = f"Copied {result.copied} photos"
        if result.skipped:
            message += f", {result.skipped} were already there"
        if self._cancel.is_set():
            message += " (cancelled)"
        message += "."
        if result.renamed:
            message += f"\n{len(result.renamed)} saved with a new name because of a name clash."
        if result.failed:
            message += f"\n{len(result.failed)} failed:\n" + "\n".join(
                f"{path.name}: {error}" for path, error in result.failed[:10]
            )
        self.status_label.setText(message.splitlines()[0])
        self._notify(message)
        self.import_done.emit(result)

    # Task plumbing

    def _run(self, label: str, task, on_done: Callable[[object], None]) -> None:
        self._set_busy(True)
        self.status_label.setText(f"{label}…")
        self.progress_bar.setRange(0, 0)
        worker = Worker(task)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(lambda result: self._finish(on_done, result))
        worker.signals.failed.connect(self._on_failed)
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    def _finish(self, on_done: Callable[[object], None], result: object) -> None:
        self._set_busy(False)
        on_done(result)
        self._run_pending_card()

    def _run_pending_card(self) -> None:
        card, self._pending_card = self._pending_card, None
        if card is not None and not self._busy:
            self.on_card_inserted(card)

    def _on_progress(self, label: str, done: int, total: int) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status_label.setText(f"{label}: {done:,} / {total:,}")

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.cancel_button.setVisible(False)
        self.status_label.setText("Failed.")
        self._show_error(message)
        self.task_failed.emit(message)
        self._run_pending_card()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress_bar.setVisible(busy)
        for widget in (
            self.change_root_button,
            self.rescan_button,
            self.find_button,
            self.detect_button,
            self.browse_source_button,
            self.include_deleted_check,
            self.include_older_check,
        ):
            widget.setEnabled(not busy)
        if busy:
            self.import_button.setEnabled(False)

    # Dialogs (separate methods so tests can replace them)

    def _ask_camera(self, group: CameraGroup) -> Camera | None:
        dialog = CameraDialog(
            group.camera,
            len(self.plan.to_copy(group)) if self.plan else 0,
            group.library_match,
            self.camera_folders,
            self,
        )
        return dialog.camera() if dialog.exec() == CameraDialog.DialogCode.Accepted else None

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(self, "Photo Importer", text)
        return answer == QMessageBox.StandardButton.Yes

    def _notify(self, text: str) -> None:
        QMessageBox.information(self, "Photo Importer", text)

    def _show_error(self, text: str) -> None:
        QMessageBox.warning(self, "Photo Importer", text)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.card_watcher.stop()
        self._cancel.set()
        QThreadPool.globalInstance().waitForDone()
        self.db.close()
        super().closeEvent(event)
