from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Camera, safe_folder_name
from .theme import muted


class CameraDialog(QDialog):
    """Asks for a new camera's name and folders before its first import."""

    def __init__(
        self,
        camera: Camera,
        photo_count: int,
        library_match: bool,
        camera_folders: list[str],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._camera = camera
        self.setWindowTitle("New camera")
        layout = QVBoxLayout(self)

        model = " ".join(filter(None, (camera.make, camera.model))) or "Photos without camera info"
        photos = "1 photo" if photo_count == 1 else f"{photo_count} photos"
        intro = f"<b>{model}</b><br>{photos} to import from a camera seen for the first time."
        if library_match:
            intro += "<br>The folders below are the ones this camera already uses in your library."
        heading = QLabel(intro)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        form = QFormLayout()
        self.nickname_edit = QLineEdit(camera.nickname)
        self.folder_combo = QComboBox()
        self.folder_combo.setEditable(True)
        self.folder_combo.addItems(camera_folders)
        self.folder_combo.setCurrentText(camera.folder_name)
        self.jpg_edit = QLineEdit(camera.jpg_dir)
        self.raw_edit = QLineEdit(camera.raw_dir)
        self.preview = muted(QLabel())
        form.addRow("Name", self.nickname_edit)
        form.addRow("Camera folder", self.folder_combo)
        form.addRow("JPG subfolder", self.jpg_edit)
        form.addRow("RAW subfolder", self.raw_edit)
        form.addRow("", self.preview)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.folder_combo.currentTextChanged.connect(self._refresh)
        self.jpg_edit.textChanged.connect(self._refresh)
        self.raw_edit.textChanged.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _clean(text: str) -> str:
        text = text.strip()
        return safe_folder_name(text) if text else ""

    def camera(self) -> Camera:
        return replace(
            self._camera,
            nickname=self.nickname_edit.text().strip() or self._camera.nickname,
            folder_name=self._clean(self.folder_combo.currentText()),
            jpg_dir=self._clean(self.jpg_edit.text()),
            raw_dir=self._clean(self.raw_edit.text()),
        )

    def _refresh(self) -> None:
        cam = self.camera()
        valid = bool(cam.folder_name)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
        if valid:
            jpg, raw = (str(Path(cam.folder_name, d)) for d in (cam.jpg_dir, cam.raw_dir))
            self.preview.setText(f"JPGs go to …{jpg}, RAWs to …{raw}")
        else:
            self.preview.setText("Enter a camera folder name.")
