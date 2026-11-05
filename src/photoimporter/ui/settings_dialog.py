from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.config import (
    ACCENTS,
    DATE_FORMAT_PRESETS,
    accent_choice,
    appearance,
    check_for_updates,
    date_format,
    exiftool_setting,
    find_on_insert,
    is_valid_date_format,
    new_import_folder,
    photos_root,
)
from ..core.db import Database
from ..core.exif import ExifToolNotFound, find_exiftool
from ..core.models import Camera, safe_folder_name
from ..core.updates import Release, newer_release
from .theme import accent_color, colors, muted

APPEARANCE_LABELS = {"system": "Same as Windows", "light": "Light", "dark": "Dark"}


class AccentPicker(QWidget):
    """A row of round colour swatches; the first is Windows' own accent colour."""

    def __init__(self, choice: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.choice = choice
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.buttons: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        for name in ("system", *ACCENTS):
            button = QToolButton()
            button.setCheckable(True)
            button.setFixedSize(26, 26)
            button.setToolTip(self.label(name))
            color = accent_color(name).name()
            button.setStyleSheet(
                f"QToolButton {{ background: {color}; border: 2px solid {color};"
                " border-radius: 13px; padding: 0; font-weight: 700; }"
                "QToolButton:checked { border: 3px solid palette(window-text); }"
            )
            if name == "system":
                button.setText("W")
                button.setStyleSheet(button.styleSheet() + "QToolButton { color: white; }")
            button.setChecked(name == choice)
            button.clicked.connect(lambda _=False, name=name: self._choose(name))
            group.addButton(button)
            layout.addWidget(button)
            self.buttons[name] = button
        self.name_label = muted(QLabel(self.label(choice)))
        layout.addSpacing(6)
        layout.addWidget(self.name_label)
        layout.addStretch(1)

    @staticmethod
    def label(name: str) -> str:
        return "Same as Windows" if name == "system" else name.capitalize()

    def _choose(self, name: str) -> None:
        self.choice = name
        self.name_label.setText(self.label(name))


_CAMERA_COLUMNS = ["Camera", "Name", "Camera folder", "JPG subfolder", "RAW subfolder"]


def exiftool_status(path: str | None) -> str:
    """Which ExifTool will be used, and its version, for the settings screen."""
    try:
        exe = path if path else find_exiftool()
        if not Path(exe).is_file():
            return f"Not found: {exe}"
        proc = subprocess.run(
            [exe, "-ver"],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        version = proc.stdout.strip()
        return f"Version {version}: {exe}" if version else f"Not working: {exe}"
    except ExifToolNotFound:
        return "Not found. Install ExifTool or choose exiftool.exe."
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Not working: {exc}"


class SettingsDialog(QDialog):
    def __init__(
        self,
        db: Database,
        parent: QWidget | None = None,
        update_checker: Callable[[], Release | None] = newer_release,
    ):
        super().__init__(parent)
        self.db = db
        self.update_checker = update_checker
        self.setWindowTitle("Settings")
        self.resize(760, 420)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_general(), "General")
        tabs.addTab(self._build_cameras(), "Cameras")
        layout.addWidget(tabs)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh_date_preview()
        self._refresh_exiftool_status()

    # General

    def _build_general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.root_edit = QLineEdit(str(photos_root(self.db)))
        self.root_edit.textChanged.connect(self._refresh_date_preview)
        browse_root = QPushButton("Browse…")
        browse_root.clicked.connect(self._browse_root)
        form.addRow("Photo library", self._row(self.root_edit, browse_root))

        self.date_combo = QComboBox()
        self.date_combo.setEditable(True)
        self.date_combo.addItems(DATE_FORMAT_PRESETS)
        self.date_combo.setCurrentText(date_format(self.db))
        self.date_combo.setToolTip(
            "YYYY = 2026, YY = 26, MM = 03, M = 3, DD = 07, D = 7. Older folders keep their names."
        )
        self.date_combo.currentTextChanged.connect(self._refresh_date_preview)
        self.date_preview = muted(QLabel())
        form.addRow("New folder date", self.date_combo)
        form.addRow("", self.date_preview)

        self.find_on_insert_check = QCheckBox("Look for new photos as soon as a card is inserted")
        self.find_on_insert_check.setChecked(find_on_insert(self.db))
        form.addRow("SD cards", self.find_on_insert_check)

        self.appearance_combo = QComboBox()
        for value, label in APPEARANCE_LABELS.items():
            self.appearance_combo.addItem(label, value)
        self.appearance_combo.setCurrentIndex(self.appearance_combo.findData(appearance(self.db)))
        form.addRow("Appearance", self.appearance_combo)

        self.accent_picker = AccentPicker(accent_choice(self.db))
        form.addRow("Accent colour", self.accent_picker)

        self.exiftool_edit = QLineEdit(exiftool_setting(self.db) or "")
        self.exiftool_edit.setPlaceholderText("Automatic")
        self.exiftool_edit.editingFinished.connect(self._refresh_exiftool_status)
        browse_exiftool = QPushButton("Browse…")
        browse_exiftool.clicked.connect(self._browse_exiftool)
        self.exiftool_status = QLabel()
        self.exiftool_status.setWordWrap(True)
        muted(self.exiftool_status)
        form.addRow("ExifTool", self._row(self.exiftool_edit, browse_exiftool))
        form.addRow("", self.exiftool_status)

        self.updates_check = QCheckBox("Check for a new version when the app starts")
        self.updates_check.setChecked(check_for_updates(self.db))
        self.check_now_button = QPushButton("Check now")
        self.check_now_button.clicked.connect(self._check_now)
        form.addRow(
            f"Updates (v{__version__})", self._row(self.updates_check, self.check_now_button)
        )
        self.update_status = QLabel()
        self.update_status.setOpenExternalLinks(True)
        self.update_status.setWordWrap(True)
        form.addRow("", self.update_status)
        return page

    def _check_now(self) -> None:
        self.update_status.setText("Checking…")
        self.update_status.repaint()
        try:
            release = self.update_checker()
        except OSError as exc:
            self.update_status.setText(f"Couldn't check for updates: {exc}")
            return
        if release is None:
            self.update_status.setText(f"You have the latest version ({__version__}).")
        else:
            self.update_status.setText(
                f'Version {release.version} is available: <a href="{release.page_url}">'
                "what's new and download</a>."
            )

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widgets[0], stretch=1)
        for widget in widgets[1:]:
            layout.addWidget(widget)
        return row

    def _browse_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Photo library folder", self.root_edit.text()
        )
        if folder:
            self.root_edit.setText(str(Path(folder)))
            self._refresh_date_preview()

    def _browse_exiftool(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "ExifTool program", self.exiftool_edit.text(), "Programs (*.exe);;All files (*)"
        )
        if path:
            self.exiftool_edit.setText(str(Path(path)))
            self._refresh_exiftool_status()

    def _refresh_date_preview(self) -> None:
        pattern = self.date_combo.currentText().strip()
        valid = is_valid_date_format(pattern)
        ok = (
            self.buttons.button(QDialogButtonBox.StandardButton.Ok)
            if hasattr(self, "buttons")
            else None
        )
        if ok:
            ok.setEnabled(valid)
        if valid:
            folder = new_import_folder(
                Path(self.root_edit.text()), "Description", date.today(), pattern
            )
            self.date_preview.setText(f"New folders will be named like: {folder.name}")
            self.date_preview.setStyleSheet("")  # the muted grey set when it was made
        else:
            self.date_preview.setText(
                "Needs a year (YYYY or YY), month (MM or M) and day (DD or D)."
            )
            self.date_preview.setStyleSheet(f"color: {colors().error}")

    def _refresh_exiftool_status(self) -> None:
        self.exiftool_status.setText(exiftool_status(self.exiftool_edit.text().strip() or None))

    # Cameras

    def _build_cameras(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Where each camera's photos go inside an import folder. Changes apply to future "
            "imports only; existing folders are never renamed."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.camera_table = QTableWidget(0, len(_CAMERA_COLUMNS))
        self.camera_table.setHorizontalHeaderLabels(_CAMERA_COLUMNS)
        self.camera_table.verticalHeader().setVisible(False)
        self.camera_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.camera_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._cameras = sorted(self.db.cameras().values(), key=lambda c: c.nickname.lower())
        for camera in self._cameras:
            self._add_camera_row(camera)
        layout.addWidget(self.camera_table)

        self.forget_button = QPushButton("Forget camera")
        self.forget_button.setToolTip(
            "You'll be asked for its folders again next time it's imported."
        )
        self.forget_button.clicked.connect(self._forget_selected)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.forget_button)
        layout.addLayout(row)
        return page

    def _add_camera_row(self, camera: Camera) -> None:
        row = self.camera_table.rowCount()
        self.camera_table.insertRow(row)
        label = QTableWidgetItem(
            " ".join(filter(None, (camera.make, camera.model))) or "No camera info"
        )
        label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.camera_table.setItem(row, 0, label)
        for col, value in enumerate(
            (camera.nickname, camera.folder_name, camera.jpg_dir, camera.raw_dir), 1
        ):
            self.camera_table.setItem(row, col, QTableWidgetItem(value))

    def _forget_selected(self) -> None:
        rows = sorted({i.row() for i in self.camera_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.camera_table.removeRow(row)
            del self._cameras[row]

    def edited_cameras(self) -> list[Camera]:
        def text(row: int, col: int) -> str:
            return self.camera_table.item(row, col).text().strip()

        def folder(value: str) -> str:
            return safe_folder_name(value) if value else ""

        result = []
        for row, camera in enumerate(self._cameras):
            result.append(
                Camera(
                    camera.make,
                    camera.model,
                    text(row, 1) or camera.nickname,
                    folder(text(row, 2)) or camera.folder_name,
                    folder(text(row, 3)),  # empty: photos go straight into the camera folder
                    folder(text(row, 4)),
                )
            )
        return result

    # Saving

    def accept(self) -> None:
        self.db.set_setting("photos_root", str(Path(self.root_edit.text().strip())))
        self.db.set_setting("date_format", self.date_combo.currentText().strip())
        self.db.set_setting("find_on_insert", "1" if self.find_on_insert_check.isChecked() else "0")
        self.db.set_setting("exiftool_path", self.exiftool_edit.text().strip())
        self.db.set_setting("appearance", self.appearance_combo.currentData())
        self.db.set_setting("accent", self.accent_picker.choice)
        self.db.set_setting("check_updates", "1" if self.updates_check.isChecked() else "0")
        kept = self.edited_cameras()
        for key in set(self.db.cameras()) - {(c.make, c.model) for c in kept}:
            self.db.delete_camera(*key)
        for camera in kept:
            self.db.save_camera(camera)
        super().accept()
