from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .. import __version__
from ..core.cameras import LibraryLayout, apply_camera_suggestions
from ..core.cards import detect_cards, scan_source
from ..core.config import (
    accent_choice,
    appearance,
    apply_exiftool_setting,
    check_for_updates,
    date_format,
    find_on_insert,
    new_import_folder,
    photos_root,
)
from ..core.copier import CopyResult, execute_plan
from ..core.db import Database
from ..core.deleter import DeleteResult, Recycler, default_recycler, delete_from_card, staging_root
from ..core.exif import ExifToolReader, MetadataReader
from ..core.indexer import ScanResult, scan_library
from ..core.models import Camera
from ..core.planner import (
    CameraGroup,
    ImportBreakdown,
    ImportPlan,
    build_plan,
    card_subtitle,
    card_title,
    import_breakdown,
)
from ..core.thumbnails import ExifToolThumbnails, ThumbnailSource, group_shots
from ..core.updates import Release, newer_release
from .camera_dialog import CameraDialog
from .card_watcher import CardWatcher
from .import_dialog import ImportConfirmDialog
from .settings_dialog import SettingsDialog
from .theme import accent, apply_appearance, colors, icon, muted, set_icon
from .thumbnail_grid import ThumbnailGrid
from .workers import BackgroundCall, ReportProgress, Worker

GEOMETRY_SETTING = "window_geometry"
THUMBNAIL_SIZE_SETTING = "thumbnail_size"  # index into thumbnail_grid.SIZES
FIRST_SIZE = QSize(1280, 900)  # fits a 1080p screen with the taskbar and title bar


class ElidedLabel(QLabel):
    """One line of text, cut off with … when it doesn't fit; the full text is the tooltip.

    Unlike a plain QLabel, a long text doesn't force the window to be wider.
    """

    def __init__(self, text: str = "", elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight):
        super().__init__(text)
        self.elide = elide
        self.setToolTip(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt name)
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        metrics = self.fontMetrics()
        text = metrics.elidedText(self.text(), self.elide, self.width())
        painter.drawText(self.rect(), int(self.alignment()), text)


def _photos(n: int) -> str:
    return f"{n} photo" if n == 1 else f"{n} photos"


class MainWindow(QMainWindow):
    plan_ready = Signal(object)
    import_done = Signal(object)
    task_failed = Signal(str)
    update_checked = Signal(object)  # Release or None

    def __init__(
        self,
        db_path: Path,
        reader_factory: Callable[[], MetadataReader] = ExifToolReader,
        card_detector: Callable[[], list[Path]] = detect_cards,
        card_poll_ms: int = 2000,
        thumbnail_factory: Callable[[], ThumbnailSource] = ExifToolThumbnails,
        update_checker: Callable[[], Release | None] | None = newer_release,
        recycler_factory: Callable[[], Recycler | None] = default_recycler,
        deleted_staging: Path | None = None,
    ):
        super().__init__()
        self.db_path = db_path
        self.reader_factory = reader_factory
        self.card_detector = card_detector
        self.thumbnail_factory = thumbnail_factory
        self.recycler = recycler_factory()
        self.deleted_staging = deleted_staging or staging_root()
        self.db = Database(db_path)
        apply_exiftool_setting(self.db)
        self.plan: ImportPlan | None = None
        self.camera_folders: list[str] = []
        self._worker: Worker | None = None
        self._cancel = threading.Event()
        self._busy = False
        self._pending_card: Path | None = None
        self._source: Path | None = None
        self._closed = False

        self.setWindowTitle("Photo Importer")
        central = QWidget()
        central.setObjectName("central")  # the stylesheet paints its background
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_update_bar())
        layout.addLayout(self._build_header())
        setup = QFrame()
        setup.setObjectName("panel")
        setup.setLayout(self._build_setup())
        setup.layout().setContentsMargins(16, 12, 16, 12)
        layout.addWidget(setup)
        layout.addWidget(self._build_plan_box(), stretch=1)
        layout.addLayout(self._build_footer())
        self.setCentralWidget(central)
        self._restore_geometry()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_appearance(app, appearance(self.db), accent_choice(self.db))
            # Windows switching between light and dark ("Same as Windows").
            app.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)
        self._apply_styles()

        self._refresh_library_label()
        self._refresh_target_preview()
        self.status_label.setText("Insert an SD card, or browse to a card or folder.")
        self.card_watcher = CardWatcher(card_detector, card_poll_ms, self)
        self.card_watcher.inserted.connect(self.on_card_inserted)
        self.card_watcher.removed.connect(self.on_card_removed)
        self.card_watcher.start()

        self.update_checker = update_checker
        self._update_call: BackgroundCall | None = None
        if update_checker is not None and check_for_updates(self.db):
            self.check_for_update()

    # Layout

    def _apply_styles(self) -> None:
        """Styles with colours of their own, for the current light/dark palette."""
        c = colors()
        color = accent()
        light, dark = color.lighter(118).name(), color.darker(118).name()
        self.import_button.setStyleSheet(
            "#importButton { color: white; font-weight: 600; border: none; border-radius: 11px;"
            " padding: 9px 22px;"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {light},"
            f" stop:0.5 {color.name()}, stop:1 {dark}); }}"
            f"#importButton:hover {{ background: {light}; }}"
            f"#importButton:pressed {{ background: {dark}; }}"
            f"#importButton:disabled {{ background: {c.disabled_bg}; color: {c.disabled_text}; }}"
        )
        self.update_bar.setStyleSheet(
            f"#updateBar {{ background: {c.banner_bg}; border: 1px solid {c.banner_border};"
            " border-radius: 12px; }"
        )

    def _on_color_scheme_changed(self, *_: object) -> None:
        app = QApplication.instance()
        if self._closed or not isinstance(app, QApplication):
            return
        if appearance(self.db) == "system":
            apply_appearance(app, "system", accent_choice(self.db))
        # Once the style has updated the palette.
        QTimer.singleShot(0, self._restyle)

    def _restyle(self) -> None:
        if not self._closed:
            self._apply_styles()
            self.grid.restyle()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt name)
        palette_events = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
        if event.type() in palette_events and hasattr(self, "import_button"):
            self._apply_styles()  # light/dark switched
        super().changeEvent(event)

    def _build_update_bar(self) -> QFrame:
        self.update_bar = QFrame()
        self.update_bar.setObjectName("updateBar")
        row = QHBoxLayout(self.update_bar)
        row.setContentsMargins(10, 4, 4, 4)
        self.update_label = QLabel()
        self.update_download_button = QPushButton("What's new && download")
        self.update_download_button.clicked.connect(self._open_update)
        self.update_skip_button = QPushButton("Skip this version")
        self.update_skip_button.clicked.connect(self._skip_update)
        self.update_close_button = QPushButton("Not now")
        self.update_close_button.clicked.connect(self.update_bar.hide)
        row.addWidget(self.update_label, stretch=1)
        for button in (
            self.update_download_button,
            self.update_skip_button,
            self.update_close_button,
        ):
            row.addWidget(button)
        self.update_bar.hide()
        self.available_update: Release | None = None
        return self.update_bar

    def _build_header(self) -> QHBoxLayout:
        """The card's title and summary, the card chooser and the round buttons."""
        row = QHBoxLayout()
        row.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = QLabel("Photo Importer")
        self.title_label.setObjectName("title")
        self.subtitle_label = muted(ElidedLabel())
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        row.addLayout(text, stretch=1)

        self.card_button = QToolButton()
        self.card_button.setObjectName("cardButton")
        self.card_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.card_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        set_icon(self.card_button, "hard-drive")
        self.card_menu = QMenu(self)
        self.card_menu.aboutToShow.connect(self._fill_card_menu)
        self.card_button.setMenu(self.card_menu)
        self.find_button = QPushButton("Find new photos")
        self.find_button.setDefault(True)
        set_icon(self.find_button, "search")
        self.find_button.clicked.connect(self.find_new_photos)
        self.rescan_button = self._round_button("refresh-cw", "Rescan library")
        self.rescan_button.clicked.connect(self.rescan_library)
        self.settings_button = self._round_button("settings", "Settings")
        self.settings_button.clicked.connect(self.open_settings)
        for widget in (
            self.card_button,
            self.find_button,
            self.rescan_button,
            self.settings_button,
        ):
            row.addWidget(widget, alignment=Qt.AlignmentFlag.AlignTop)
        self._refresh_card_button()
        return row

    @staticmethod
    def _round_button(icon_name: str, tip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("roundButton")
        button.setToolTip(tip)
        set_icon(button, icon_name)
        return button

    def source(self) -> Path | None:
        """The SD card or folder to import from."""
        return self._source

    def set_source(self, path: Path | str | None) -> None:
        self._source = Path(path) if path else None
        self._refresh_card_button()
        self._refresh_header()

    def _refresh_card_button(self) -> None:
        source = self._source
        if source is None:
            self.card_button.setText("Choose a card")
            self.card_button.setToolTip("Choose an SD card or a folder to import from")
        else:
            drive = source == Path(source.anchor) and bool(source.anchor)
            name = f"{source}  SD card" if drive else source.name or str(source)
            self.card_button.setText(name)
            self.card_button.setToolTip(f"Importing from {source}")

    def _fill_card_menu(self) -> None:
        self.card_menu.clear()
        try:
            cards = list(self.card_detector())
        except OSError:
            cards = []
        for card in cards:
            action = self.card_menu.addAction(icon("hard-drive"), f"{card}  SD card")
            action.triggered.connect(lambda _=False, card=card: self._use_card(card))
        if not cards:
            self.card_menu.addAction("No SD card found").setEnabled(False)
        self.card_menu.addSeparator()
        self.card_menu.addAction(icon("folder-open"), "Choose a folder…", self.choose_source)

    def _use_card(self, card: Path) -> None:
        self.set_source(card)
        self.find_new_photos()

    def _refresh_header(self) -> None:
        self.title_label.setText(card_title(self.plan, self._source))
        self.subtitle_label.setText(card_subtitle(self.plan))

    def _build_setup(self) -> QGridLayout:
        """Library, import folder and card, one compact row each."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        # Cut off in the middle, keeping the drive and the photo count, if it doesn't fit.
        self.library_label = ElidedLabel(elide=Qt.TextElideMode.ElideMiddle)
        self.change_root_button = QPushButton("Change…")
        self.change_root_button.clicked.connect(self.choose_photos_root)

        self.new_radio = QRadioButton("New folder")
        self.existing_radio = QRadioButton("Existing folder")
        self.new_radio.setChecked(True)
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Description, e.g. Halloween Hike")
        self.target_preview = QLabel()
        muted(self.target_preview)
        # Ignored width: a long path is cut off instead of squeezing the description box.
        self.target_preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.existing_edit = QLineEdit()
        self.existing_edit.setPlaceholderText("Choose a folder in your library")
        self.browse_target_button = QPushButton("Browse…")
        self.browse_target_button.clicked.connect(self.choose_existing_target)
        for signal in (
            self.new_radio.toggled,
            self.description_edit.textChanged,
            self.existing_edit.textChanged,
        ):
            signal.connect(self._refresh_target_preview)

        def caption(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet("font-weight: 600")
            return label

        def buttons(*widgets: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addStretch(1)
            for widget in widgets:
                row.addWidget(widget)
            return row

        grid.addWidget(caption("Library"), 0, 0)
        grid.addWidget(self.library_label, 0, 1, 1, 2)
        grid.addLayout(buttons(self.change_root_button), 0, 3)
        grid.addWidget(caption("Import into"), 1, 0)
        grid.addWidget(self.new_radio, 1, 1)
        new_row = QHBoxLayout()
        new_row.setSpacing(10)
        new_row.addWidget(self.description_edit, stretch=1)
        new_row.addWidget(self.target_preview, stretch=1)
        grid.addLayout(new_row, 1, 2, 1, 2)
        grid.addWidget(self.existing_radio, 2, 1)
        grid.addWidget(self.existing_edit, 2, 2)
        grid.addLayout(buttons(self.browse_target_button), 2, 3)
        grid.setColumnStretch(2, 1)
        return grid

    def _build_plan_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.grid = ThumbnailGrid(self.thumbnail_factory)
        self.grid.selection_changed.connect(self._refresh_selection_view)
        self.grid.delete_requested.connect(self.delete_selected)
        saved = self.db.get_setting(THUMBNAIL_SIZE_SETTING)
        if saved and saved.isdigit():
            self.grid.set_thumbnail_size(int(saved))
        self.grid.size_changed.connect(
            lambda index: self.db.set_setting(THUMBNAIL_SIZE_SETTING, str(index))
        )
        layout.addWidget(self.grid)
        # Only shown when the card has photos from more than one camera.
        self.camera_combo = QComboBox()
        self.camera_combo.setToolTip("Show the photos from one camera only")
        self.camera_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.camera_combo.currentIndexChanged.connect(self._refresh_grid)
        self.camera_combo.setVisible(False)
        self.grid.toolbar.insertWidget(2, self.camera_combo)

        self.include_recent_deleted_check = QCheckBox()
        self.include_recent_deleted_check.setToolTip(
            "Photos you deleted that are newer than any photo from the same camera still in\n"
            "your library, for example after deleting your latest import folder."
        )
        self.include_deleted_check = QCheckBox()
        self.include_deleted_check.setToolTip(
            "Photos that were imported before and later deleted from your library,\n"
            "for example during a cleanup in Capture One."
        )
        self.include_older_check = QCheckBox()
        self.include_older_check.setToolTip(
            "Photos that are not in your library but are older than the newest photo\n"
            "already there from the same camera, so they were most likely imported and\n"
            "deleted before the app kept a history."
        )
        self.allow_reimport_check = QCheckBox("Allow re-importing photos already in the library")
        self.allow_reimport_check.setToolTip(
            "Lets you select photos that are already in your library, to copy them again\n"
            "into this import folder. Off each time you look at a card."
        )
        self.allow_reimport_check.toggled.connect(self._on_allow_reimport)
        self.include_already_check = QCheckBox()
        self.include_already_check.setToolTip("Copies these photos again into this import folder.")

        # The Include menu: one tick per kind of photo that is skipped unless you ask for it.
        self.include_menu = QMenu(self)
        self._include_actions: dict[QCheckBox, QWidgetAction] = {}
        for status, check in self._include_checks().items():
            check.clicked.connect(lambda on, status=status: self._on_include_clicked(status, on))
            if status == "already":
                self.include_menu.addSeparator()
                self._add_menu_check(self.allow_reimport_check)
            self._add_menu_check(check, indent=20 if status == "already" else 0)
        self.include_button = QToolButton()
        self.include_button.setText("Include")
        self.include_button.setMenu(self.include_menu)
        self.include_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.include_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_icon(self.include_button, "filter")
        self.grid.toolbar.insertWidget(3, self.include_button)
        self._refresh_include_checks()
        return box

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.status_label = ElidedLabel("Ready.")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel.set)
        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("importButton")
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

    # Updates

    def check_for_update(self) -> None:
        """Look for a newer release in the background; show a bar if there is one."""
        call = BackgroundCall(self.update_checker)
        call.signals.finished.connect(self._on_update_checked)
        call.signals.failed.connect(lambda _message: self.update_checked.emit(None))  # offline
        self._update_call = call
        QThreadPool.globalInstance().start(call)

    def _on_update_checked(self, release: Release | None) -> None:
        if release is not None and release.version != self.db.get_setting("skipped_version"):
            self.available_update = release
            self.update_label.setText(
                f"<b>Photo Importer {release.version}</b> is available (you have {__version__})."
            )
            self.update_bar.show()
        self.update_checked.emit(release)

    def _open_update(self) -> None:
        if self.available_update is not None:
            QDesktopServices.openUrl(QUrl(self.available_update.page_url))

    def _skip_update(self) -> None:
        if self.available_update is not None:
            self.db.set_setting("skipped_version", self.available_update.version)
        self.update_bar.hide()

    # Settings

    def open_settings(self) -> None:
        if self._exec_settings():
            self._apply_settings()

    def _exec_settings(self) -> bool:
        dialog = SettingsDialog(self.db, self, self.update_checker or newer_release)
        return dialog.exec() == SettingsDialog.DialogCode.Accepted

    def _apply_settings(self) -> None:
        apply_exiftool_setting(self.db)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_appearance(app, appearance(self.db), accent_choice(self.db))
            self._restyle()
        self._refresh_library_label()
        self._refresh_target_preview()
        if self.plan is not None:
            # Camera names and folders may have changed.
            cameras = self.db.cameras()
            for group in self.plan.groups:
                camera = cameras.get((group.camera.make, group.camera.model))
                if camera is not None:
                    group.camera, group.registered = camera, True
                elif group.registered:
                    group.camera = Camera.default_for(group.camera.make, group.camera.model)
                    group.registered = False
            self._refresh_plan_view()

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
            return new_import_folder(
                photos_root(self.db), description, date.today(), date_format(self.db)
            )
        text = self.existing_edit.text().strip()
        return Path(text) if text else None

    def _refresh_target_preview(self) -> None:
        is_new = self.new_radio.isChecked()
        self.description_edit.setEnabled(is_new)
        self.existing_edit.setEnabled(not is_new)
        self.browse_target_button.setEnabled(not is_new)
        target = self.target_dir() if is_new else None
        self.target_preview.setText(str(target) if target else "")
        self.target_preview.setToolTip(f"This import will create {target}" if target else "")

    def choose_existing_target(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import folder", str(photos_root(self.db)))
        if folder:
            self.existing_edit.setText(str(Path(folder)))

    def choose_source(self) -> None:
        start = str(self._source) if self._source else ""
        folder = QFileDialog.getExistingDirectory(self, "SD card or folder", start)
        if folder:
            self.set_source(Path(folder))
            self.find_new_photos()

    def detect_card(self) -> None:
        cards = self.card_detector()
        if cards:
            self.set_source(cards[0])
            self.status_label.setText(f"Card detected: {', '.join(map(str, cards))}")
        else:
            self.status_label.setText("No card detected. Browse to a card or folder.")

    def on_card_inserted(self, card: Path) -> None:
        """A card was inserted (or was already in when the app started): look at it."""
        if not find_on_insert(self.db):
            if not self._busy:
                self.set_source(card)
                self.status_label.setText(f"Card inserted: {card}. Click Find new photos.")
            return
        if self._busy:
            self._pending_card = card
            self.status_label.setText(f"Card inserted: {card}. Checking it when this finishes…")
            return
        self.set_source(card)
        self.find_new_photos()

    def on_card_removed(self, card: Path) -> None:
        if self._pending_card == card:
            self._pending_card = None
        if self._busy or self._source != card:
            return
        self._set_plan(None)
        self.status_label.setText(f"Card removed: {card}.")

    # Planning

    def find_new_photos(self) -> None:
        source = self._source
        if source is None or not source.is_dir():
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
                    db.newest_capture_by_model(include_deleted=False),
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
        """Show a fresh plan: only new photos ticked, re-importing not allowed."""
        self.plan = plan
        self.allow_reimport_check.blockSignals(True)
        self.allow_reimport_check.setChecked(False)
        self.allow_reimport_check.blockSignals(False)
        self._refresh_plan_view()

    def _on_include_clicked(self, status: str, on: bool) -> None:
        """An Include tick was clicked: tick or untick all photos with that status."""
        if self.plan is not None:
            self.plan.select(self.plan.photos(status), on)
            self.grid.refresh_checks()
        self._refresh_selection_view()

    def _on_allow_reimport(self, allow: bool) -> None:
        if self.plan is not None:
            self.plan.allow_reimport = allow
            self.grid.refresh_checks()
        self._refresh_selection_view()

    def _refresh_plan_view(self) -> None:
        plan = self.plan
        self._refresh_header()
        self._refresh_include_checks()
        self._refresh_camera_combo()
        if plan is None:
            self.grid.set_plan(None)
            self.import_button.setEnabled(False)
            self.import_button.setText("Import")
            return
        self._refresh_grid()
        self._refresh_selection_view()

    def _refresh_camera_combo(self) -> None:
        """List the plan's cameras, keeping the chosen one if it's still there."""
        chosen = self.camera_combo.currentData()
        groups = self.plan.groups if self.plan else []
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        self.camera_combo.addItem(f"All cameras ({self._pictures(groups)})", None)
        for group in groups:
            cam = group.camera
            name = cam.nickname if group.registered else f"{cam.nickname} (new camera)"
            self.camera_combo.addItem(f"{name} ({self._pictures([group])})", (cam.make, cam.model))
        index = self.camera_combo.findData(chosen) if chosen is not None else 0
        self.camera_combo.setCurrentIndex(max(index, 0))
        self.camera_combo.blockSignals(False)
        self.camera_combo.setVisible(len(groups) > 1)

    @staticmethod
    def _pictures(groups: list[CameraGroup]) -> int:
        return len(group_shots([p for g in groups for p in g.photos()]))

    def shown_groups(self) -> list[CameraGroup]:
        """The camera groups shown in the grid: the one chosen, or all of them."""
        if self.plan is None:
            return []
        chosen = self.camera_combo.currentData()
        return [
            g
            for g in self.plan.groups
            if chosen is None or (g.camera.make, g.camera.model) == chosen
        ]

    def _refresh_selection_view(self) -> None:
        """Update everything that depends on which photos are ticked, without redrawing the grid."""
        plan = self.plan
        self._refresh_include_checks()
        if plan is None:
            self.import_button.setEnabled(False)
            self.import_button.setText("Import")
            return
        pictures, files = self._import_counts()
        self.import_button.setEnabled(files > 0)
        self.import_button.setText(f"Import {self._amount(pictures, files)}" if files else "Import")
        self.status_label.setText(plan.summary())

    def _import_counts(self) -> tuple[int, int]:
        """(pictures, files) ticked for import; a RAW+JPG pair is one picture, two files."""
        if self.plan is None:
            return 0, 0
        files = [p for g in self.plan.groups for p in self.plan.to_copy(g)]
        return len(group_shots(files)), len(files)

    @staticmethod
    def _amount(pictures: int, files: int) -> str:
        text = _photos(pictures)
        return text if files == pictures else f"{text} ({files} files)"

    def _add_menu_check(self, check: QCheckBox, indent: int = 0) -> None:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(10 + indent, 4, 12, 4)
        row.addWidget(check)
        action = QWidgetAction(self.include_menu)
        action.setDefaultWidget(holder)
        self.include_menu.addAction(action)
        self._include_actions[check] = action

    def _show_in_menu(self, check: QCheckBox, show: bool) -> None:
        self._include_actions[check].setVisible(show)

    def in_include_menu(self, check: QCheckBox) -> bool:
        """Whether `check` is offered in the Include menu (for tests)."""
        return self._include_actions[check].isVisible()

    def _include_checks(self) -> dict[str, QCheckBox]:
        return {
            "recent_deleted": self.include_recent_deleted_check,
            "deleted": self.include_deleted_check,
            "older": self.include_older_check,
            "already": self.include_already_check,
        }

    def _refresh_grid(self) -> None:
        if self.plan is None:
            self.grid.set_plan(None)
            return
        self.grid.set_plan(self.plan, self.shown_groups())

    def _refresh_include_checks(self) -> None:
        plan = self.plan
        recent = plan.recent_deleted_count if plan else 0
        deleted = plan.deleted_count if plan else 0
        older = plan.older_count if plan else 0
        already = plan.already_count if plan else 0
        self.include_already_check.setText(f"Already imported ({already})")
        self._show_in_menu(self.allow_reimport_check, already > 0)
        self._show_in_menu(
            self.include_already_check, already > 0 and self.allow_reimport_check.isChecked()
        )
        for status, check in self._include_checks().items():
            total = len(plan.photos(status)) if plan else 0
            ticked = plan.selected_count(status) if plan else 0
            if ticked == 0:
                state = Qt.CheckState.Unchecked
            elif ticked == total:
                state = Qt.CheckState.Checked
            else:
                state = Qt.CheckState.PartiallyChecked
            check.blockSignals(True)
            check.setCheckState(state)
            check.blockSignals(False)
        self.include_recent_deleted_check.setText(f"Recently deleted ({recent})")
        self.include_deleted_check.setText(f"Deleted since import ({deleted})")
        self.include_older_check.setText(f"Probably deleted earlier ({older})")
        self._show_in_menu(self.include_recent_deleted_check, recent > 0)
        self._show_in_menu(self.include_deleted_check, deleted > 0)
        self._show_in_menu(self.include_older_check, older > 0)
        # How many kinds of skipped photo are (partly) included, shown on the button.
        kinds = ["recent_deleted", "deleted", "older"]
        if self.allow_reimport_check.isChecked():
            kinds.append("already")
        included = sum(1 for k in kinds if plan and plan.selected_count(k))
        anything = bool(recent or deleted or older or already)
        self.include_button.setEnabled(anything and not self._busy)
        self.include_button.setText(f"Include ({included})" if included else "Include")
        self.include_button.setToolTip(
            "Photos skipped unless you include them: deleted from your library, or already\n"
            "imported. Their tiles show a coloured label."
            if anything
            else "Nothing to include: every photo on this card is new."
        )

    # Deleting from the card

    def delete_selected(self) -> None:
        """Delete the selected photos shown in the grid from the card, after confirming."""
        photos = self.grid.chosen_shown()
        if self._busy or self.plan is None or not photos:
            return
        amount = self._amount(len(group_shots(photos)), len(photos))
        if self.recycler is not None:
            where = (
                "They'll be moved to the Windows Recycle Bin in case you need them back. "
                f"Restoring puts them in this folder on your PC, not back on the card:\n"
                f"{self.deleted_staging}"
            )
        else:
            where = f"A copy of each is kept on this PC in:\n{self.deleted_staging}"
        if not self._confirm(f"Delete {amount} from the SD card?\n\n{where}"):
            return
        paths = [p.path for p in photos]
        recycler, staging = self.recycler, self.deleted_staging

        def task(report: ReportProgress) -> DeleteResult:
            return delete_from_card(
                paths, recycler, staging, lambda d, t: report("Deleting from card", d, t)
            )

        self.grid.stop()
        self._run("Deleting from card", task, self._on_delete_done)

    def _on_delete_done(self, result: DeleteResult) -> None:
        if self.plan is not None:
            self.plan.remove(set(result.deleted))
            self._refresh_plan_view()
        pictures = len({(p.parent, p.stem.lower()) for p in result.deleted})
        message = f"Deleted {_photos(pictures)} from the card."
        self.status_label.setText(message)
        if result.failed:
            self._notify(
                message
                + f"\n{len(result.failed)} files were kept on the card:\n"
                + "\n".join(f"{path.name}: {error}" for path, error in result.failed[:10])
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
        shown = {p.path for shot in self.grid.shots() for p in shot.photos}
        if not self._confirm_import(import_breakdown(plan, shown), target):
            return
        self.grid.stop()  # don't compete with the copy for the card
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
            self.settings_button,
            self.find_button,
            self.card_button,
            self.include_button,
            self.grid.select_all_button,
            self.grid.select_none_button,
            self.grid.list,
        ):
            widget.setEnabled(not busy)
        self.grid.delete_button.setEnabled(not busy and bool(self.grid.chosen_shown()))
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

    def _confirm_import(self, breakdown: ImportBreakdown, target: Path) -> bool:
        dialog = ImportConfirmDialog(breakdown, target, self)
        return dialog.exec() == ImportConfirmDialog.DialogCode.Accepted

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(self, "Photo Importer", text)
        return answer == QMessageBox.StandardButton.Yes

    def _notify(self, text: str) -> None:
        QMessageBox.information(self, "Photo Importer", text)

    def _show_error(self, text: str) -> None:
        QMessageBox.warning(self, "Photo Importer", text)

    def _restore_geometry(self) -> None:
        """Reopen where the window was last closed; the first time, 1280×900, centred."""
        saved = self.db.get_setting(GEOMETRY_SETTING)
        if saved and self.restoreGeometry(QByteArray.fromBase64(saved.encode())):
            return
        area = self.screen().availableGeometry()
        # Leave room for the title bar, which isn't part of the window's size.
        width, height = (
            min(FIRST_SIZE.width(), area.width()),
            min(FIRST_SIZE.height(), area.height() - 40),
        )
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)

    def _save_geometry(self) -> None:
        self.db.set_setting(GEOMETRY_SETTING, bytes(self.saveGeometry().toBase64()).decode())

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closed:  # a window can be closed twice; the database only once
            self._closed = True
            self._save_geometry()
            self.card_watcher.stop()
            self.grid.stop()
            self._cancel.set()
            QThreadPool.globalInstance().waitForDone()
            self.db.close()
        super().closeEvent(event)
