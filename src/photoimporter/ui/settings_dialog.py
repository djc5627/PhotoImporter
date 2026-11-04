from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QVBoxLayout,
    QWidget,
)

from ..core.config import (
    DATE_FORMAT_PRESETS,
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
    def __init__(self, db: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.db = db
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
        self.date_preview = QLabel()
        form.addRow("New folder date", self.date_combo)
        form.addRow("", self.date_preview)

        self.find_on_insert_check = QCheckBox("Look for new photos as soon as a card is inserted")
        self.find_on_insert_check.setChecked(find_on_insert(self.db))
        form.addRow("SD cards", self.find_on_insert_check)

        self.exiftool_edit = QLineEdit(exiftool_setting(self.db) or "")
        self.exiftool_edit.setPlaceholderText("Automatic")
        self.exiftool_edit.editingFinished.connect(self._refresh_exiftool_status)
        browse_exiftool = QPushButton("Browse…")
        browse_exiftool.clicked.connect(self._browse_exiftool)
        self.exiftool_status = QLabel()
        self.exiftool_status.setWordWrap(True)
        self.exiftool_status.setStyleSheet("color: gray")
        form.addRow("ExifTool", self._row(self.exiftool_edit, browse_exiftool))
        form.addRow("", self.exiftool_status)
        return page

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
            self.date_preview.setStyleSheet("color: gray")
        else:
            self.date_preview.setText(
                "Needs a year (YYYY or YY), month (MM or M) and day (DD or D)."
            )
            self.date_preview.setStyleSheet("color: #b00020")

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
        kept = self.edited_cameras()
        for key in set(self.db.cameras()) - {(c.make, c.model) for c in kept}:
            self.db.delete_camera(*key)
        for camera in kept:
            self.db.save_camera(camera)
        super().accept()
