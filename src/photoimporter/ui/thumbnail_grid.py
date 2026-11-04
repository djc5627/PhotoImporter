from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.models import PhotoFile
from ..core.planner import CameraGroup, ImportPlan
from ..core.thumbnails import Shot, Thumbnail, ThumbnailSource, group_shots

THUMB_SIZE = QSize(160, 120)
_ROTATIONS = {3: 180, 6: 90, 8: 270}

# (label, photos of a group shown in that view)
VIEWS: list[tuple[str, Callable[[ImportPlan, CameraGroup], list[PhotoFile]]]] = [
    ("To import", lambda plan, g: plan.to_copy(g)),
    ("New", lambda plan, g: g.new),
    ("Recently deleted", lambda plan, g: g.recent_deleted),
    ("Deleted", lambda plan, g: g.deleted),
    ("Probably deleted", lambda plan, g: g.older),
    ("Already imported", lambda plan, g: g.already),
]


def thumbnail_image(thumb: Thumbnail, path: Path) -> QImage | None:
    """Decode, rotate upright and shrink a thumbnail. Falls back to decoding a JPG itself."""
    image = QImage.fromData(thumb.data) if thumb.data else QImage()
    if image.isNull() and path.suffix.lower() in (".jpg", ".jpeg"):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)  # the file's own orientation is applied here
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(THUMB_SIZE * 2, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        thumb = Thumbnail(None, 1)
    if image.isNull():
        return None
    angle = _ROTATIONS.get(thumb.orientation)
    if angle:
        image = image.transformed(QTransform().rotate(angle))
    return image.scaled(
        THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


class _JobSignals(QObject):
    loaded = Signal(object, object)  # path, QImage or None
    finished = Signal()


class ThumbnailJob(QRunnable):
    """Loads thumbnails for `paths` in small batches, so the first ones appear quickly."""

    def __init__(self, paths: Sequence[Path], source_factory: Callable[[], ThumbnailSource]):
        super().__init__()
        self.paths = list(paths)
        self.source_factory = source_factory
        self.cancel = threading.Event()
        self.signals = _JobSignals()

    def run(self) -> None:
        try:
            self._load()
        finally:
            self.signals.finished.emit()

    def _load(self) -> None:
        try:
            source = self.source_factory()
        except Exception:
            source = None  # e.g. ExifTool missing: JPGs still load directly
        start, size = 0, 24
        while start < len(self.paths) and not self.cancel.is_set():
            batch = self.paths[start : start + size]
            try:
                thumbs = source.extract(batch) if source else {}
            except Exception:
                thumbs = {}
            for path in batch:
                if self.cancel.is_set():
                    return
                image = thumbnail_image(thumbs.get(path, Thumbnail(None)), path)
                self.signals.loaded.emit(path, image)
            start += size
            size = 120


def _placeholder(text: str) -> QPixmap:
    pixmap = QPixmap(THUMB_SIZE)
    pixmap.fill(QColor("#d8d8d8"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#777"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


class ThumbnailGrid(QWidget):
    """Thumbnails of one group of a plan's photos, with RAW+JPG pairs shown once."""

    thumbnails_loaded = Signal()

    def __init__(
        self, source_factory: Callable[[], ThumbnailSource], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.source_factory = source_factory
        self.plan: ImportPlan | None = None
        self.groups: list[CameraGroup] = []
        self.cache: dict[Path, QImage | None] = {}
        self._items: dict[Path, list[QListWidgetItem]] = {}
        self._job: ThumbnailJob | None = None
        self._running: set[ThumbnailJob] = set()  # kept alive until their thread is done
        self._loading_icon = QIcon(_placeholder("Loading…"))
        self._missing_icon = QIcon(_placeholder("No preview"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show:"))
        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self._rebuild)
        row.addWidget(self.view_combo)
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: gray")
        row.addWidget(self.count_label, stretch=1)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(THUMB_SIZE)
        self.list.setGridSize(QSize(THUMB_SIZE.width() + 16, THUMB_SIZE.height() + 36))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(self._open)
        layout.addWidget(self.list)

    # Public

    def set_plan(self, plan: ImportPlan | None, groups: list[CameraGroup] | None = None) -> None:
        """Show `plan`, limited to `groups` (all cameras if None or empty)."""
        if plan is None or (self.plan is not None and plan.source != self.plan.source):
            self.cache.clear()
        if plan is not self.plan:
            self.view_combo.blockSignals(True)
            self.view_combo.setCurrentIndex(0)
            self.view_combo.blockSignals(False)
        self.plan = plan
        self.groups = list(groups or (plan.groups if plan else []))
        self._refresh_combo()
        self._rebuild()

    def stop(self) -> None:
        if self._job is not None:
            self._job.cancel.set()
            self._job = None

    def shots(self) -> list[Shot]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    # Internals

    def _photos(self, view: int) -> list[PhotoFile]:
        if self.plan is None:
            return []
        select = VIEWS[view][1]
        return [p for g in self.groups for p in select(self.plan, g)]

    def _refresh_combo(self) -> None:
        current = max(self.view_combo.currentIndex(), 0)
        self.view_combo.blockSignals(True)
        self.view_combo.clear()
        for i, (label, _) in enumerate(VIEWS):
            self.view_combo.addItem(f"{label} ({len(self._photos(i))})")
        self.view_combo.setCurrentIndex(current)
        self.view_combo.setEnabled(self.plan is not None)
        self.view_combo.blockSignals(False)

    def _rebuild(self) -> None:
        self.stop()
        self.list.clear()
        self._items.clear()
        shots = group_shots(self._photos(max(self.view_combo.currentIndex(), 0)))
        to_load: list[Path] = []
        for shot in shots:
            item = QListWidgetItem(f"{shot.name}  {shot.badge}".strip())
            item.setData(Qt.ItemDataRole.UserRole, shot)
            item.setToolTip(self._tooltip(shot))
            item.setSizeHint(self.list.gridSize())
            path = shot.primary.path
            self._set_icon(item, path)
            if path not in self.cache and path not in self._items:
                to_load.append(path)
            self._items.setdefault(path, []).append(item)
            self.list.addItem(item)
        if self.plan is None:
            self.count_label.setText("")
        else:
            self.count_label.setText(
                f"{len(shots)} pictures" + (" (RAW+JPG pairs shown once)" if shots else "")
            )
        if to_load:
            job = ThumbnailJob(to_load, self.source_factory)
            job.setAutoDelete(False)
            job.signals.loaded.connect(self._on_loaded)
            job.signals.finished.connect(lambda: self._running.discard(job))
            self._job = job
            self._running.add(job)
            QThreadPool.globalInstance().start(job)
        elif self.plan is not None:
            self.thumbnails_loaded.emit()

    def _set_icon(self, item: QListWidgetItem, path: Path) -> None:
        if path not in self.cache:
            item.setIcon(self._loading_icon)
        elif self.cache[path] is None:
            item.setIcon(self._missing_icon)
        else:
            item.setIcon(QIcon(QPixmap.fromImage(self.cache[path])))

    def _on_loaded(self, path: Path, image: QImage | None) -> None:
        self.cache[path] = image
        for item in self._items.get(path, []):
            self._set_icon(item, path)
        if all(p in self.cache for p in self._items):
            self.thumbnails_loaded.emit()

    @staticmethod
    def _tooltip(shot: Shot) -> str:
        meta = shot.primary.meta
        lines = [" + ".join(p.filename for p in shot.photos)]
        camera = " ".join(filter(None, (meta.make, meta.model)))
        if camera:
            lines.append(camera)
        if meta.capture_time:
            date, _, time = meta.capture_time.partition(" ")
            lines.append(f"{date.replace(':', '-')} {time}")
        lines.append("Double-click to open")
        return "\n".join(lines)

    def _open(self, item: QListWidgetItem) -> None:
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(shot.primary.path)))
