from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import PhotoFile
from ..core.planner import STATUS_LABELS, STATUSES, CameraGroup, ImportPlan
from ..core.thumbnails import Shot, Thumbnail, ThumbnailSource, group_shots

THUMB_SIZE = QSize(160, 120)
_ROTATIONS = {3: 180, 6: 90, 8: 270}

# (label, photos of a group shown in that view)
VIEWS: list[tuple[str, Callable[[ImportPlan, CameraGroup], list[PhotoFile]]]] = [
    ("All on card", lambda plan, g: g.photos()),
    ("Ticked for import", lambda plan, g: plan.to_copy(g)),
    *((STATUS_LABELS[s], (lambda status: lambda plan, g: g.photos(status))(s)) for s in STATUSES),
]

STATUS_COLORS = {
    "new": "#2e7d32",
    "recent_deleted": "#e07b00",
    "deleted": "#c62828",
    "older": "#7b4fa0",
    "already": "#616161",
}


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


def _with_status(pixmap: QPixmap, status: str) -> QPixmap:
    """The thumbnail with its status as a coloured label in the top-left corner."""
    result = QPixmap(THUMB_SIZE)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(
        (THUMB_SIZE.width() - pixmap.width()) // 2,
        (THUMB_SIZE.height() - pixmap.height()) // 2,
        pixmap,
    )
    font = painter.font()
    font.setPointSizeF(max(font.pointSizeF() - 1, 7))
    font.setBold(True)
    painter.setFont(font)
    text = STATUS_LABELS[status]
    width = painter.fontMetrics().horizontalAdvance(text) + 10
    height = painter.fontMetrics().height() + 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(STATUS_COLORS[status]))
    painter.drawRoundedRect(3, 3, width, height, 4, 4)
    painter.setPen(QColor("white"))
    painter.drawText(3, 3, width, height, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return result


class ThumbnailGrid(QWidget):
    """Thumbnails of a plan's photos, one tile per shot, each with a tick box for importing.

    Ticking a tile selects all of the shot's files (a RAW+JPG pair together). Photos already
    in the library can only be ticked when `allow_reimport` is on.
    """

    thumbnails_loaded = Signal()
    selection_changed = Signal()

    def __init__(
        self, source_factory: Callable[[], ThumbnailSource], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.source_factory = source_factory
        self.plan: ImportPlan | None = None
        self.groups: list[CameraGroup] = []
        self.allow_reimport = False
        self.cache: dict[Path, QImage | None] = {}
        self._statuses: dict[Path, str] = {}
        self._items: dict[Path, list[QListWidgetItem]] = {}
        self._job: ThumbnailJob | None = None
        self._running: set[ThumbnailJob] = set()  # kept alive until their thread is done
        self._updating = False
        self._loading = QPixmap(_placeholder("Loading…"))
        self._missing = QPixmap(_placeholder("No preview"))

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
        self.tick_all_button = QPushButton("Tick all")
        self.tick_all_button.setToolTip("Tick every photo shown")
        self.tick_all_button.clicked.connect(lambda: self._tick_shown(True))
        self.untick_all_button = QPushButton("Untick all")
        self.untick_all_button.setToolTip("Untick every photo shown")
        self.untick_all_button.clicked.connect(lambda: self._tick_shown(False))
        row.addWidget(self.tick_all_button)
        row.addWidget(self.untick_all_button)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(THUMB_SIZE)
        self.list.setGridSize(QSize(THUMB_SIZE.width() + 16, THUMB_SIZE.height() + 36))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setToolTip("")
        self.list.itemDoubleClicked.connect(self._open)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.installEventFilter(self)
        layout.addWidget(self.list)
        self._refresh_buttons()

    # Public

    def set_plan(self, plan: ImportPlan | None, groups: list[CameraGroup] | None = None) -> None:
        """Show `plan`, limited to `groups` (all cameras if None or empty)."""
        if plan is None or (self.plan is not None and plan.source != self.plan.source):
            self.cache.clear()
        if plan is not self.plan:
            self.view_combo.blockSignals(True)
            self.view_combo.setCurrentIndex(0)
            self.view_combo.blockSignals(False)
            self._statuses = plan.statuses() if plan else {}
        self.plan = plan
        self.groups = list(groups or (plan.groups if plan else []))
        self._refresh_combo()
        self._rebuild()

    def set_allow_reimport(self, allow: bool) -> None:
        self.allow_reimport = allow
        self.refresh_checks()

    def refresh_checks(self) -> None:
        """Update tick boxes and counts after the plan's selection changed elsewhere."""
        self._updating = True
        for i in range(self.list.count()):
            self._apply_check(self.list.item(i))
        self._updating = False
        self._refresh_combo()
        if self._view_label() == "Ticked for import":
            self._rebuild()
        else:
            self._refresh_count()

    def stop(self) -> None:
        if self._job is not None:
            self._job.cancel.set()
            self._job = None

    def shots(self) -> list[Shot]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def item_for(self, name: str) -> QListWidgetItem:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole).name == name:
                return self.list.item(i)
        raise KeyError(name)

    # Ticking

    def _selectable(self, shot: Shot) -> list[PhotoFile]:
        return [
            p for p in shot.photos if self.allow_reimport or self._statuses.get(p.path) != "already"
        ]

    def _apply_check(self, item: QListWidgetItem) -> None:
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        selectable = self._selectable(shot)
        flags = item.flags()
        if not selectable or self.plan is None:
            item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.CheckStateRole, None)
            return
        item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
        ticked = sum(self.plan.is_selected(p) for p in selectable)
        if ticked == 0:
            state = Qt.CheckState.Unchecked
        elif ticked == len(selectable):
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        item.setCheckState(state)

    def _set_ticked(self, items: list[QListWidgetItem], on: bool) -> None:
        if self.plan is None:
            return
        for item in items:
            self.plan.select(self._selectable(item.data(Qt.ItemDataRole.UserRole)), on)
        self.refresh_checks()
        self.selection_changed.emit()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating or self.plan is None:
            return
        if not item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return
        on = item.checkState() == Qt.CheckState.Checked
        selectable = self._selectable(item.data(Qt.ItemDataRole.UserRole))
        if all(self.plan.is_selected(p) == on for p in selectable):
            return  # not a change to the tick box
        self._set_ticked([item], on)

    def _tick_shown(self, on: bool) -> None:
        self._set_ticked([self.list.item(i) for i in range(self.list.count())], on)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Space flips the tick boxes of all selected tiles together.
        if (
            obj is self.list
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
        ):
            items = [
                i for i in self.list.selectedItems() if i.flags() & Qt.ItemFlag.ItemIsUserCheckable
            ]
            if items:
                all_ticked = all(i.checkState() == Qt.CheckState.Checked for i in items)
                self._set_ticked(items, not all_ticked)
            return True
        return super().eventFilter(obj, event)

    # Internals

    def _view_label(self) -> str:
        return VIEWS[max(self.view_combo.currentIndex(), 0)][0]

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

    def _refresh_count(self) -> None:
        if self.plan is None:
            self.count_label.setText("")
            return
        shots = self.shots()
        ticked = sum(
            1
            for i in range(self.list.count())
            if self.list.item(i).checkState() != Qt.CheckState.Unchecked
            and self.list.item(i).flags() & Qt.ItemFlag.ItemIsUserCheckable
        )
        self.count_label.setText(f"{len(shots)} pictures, {ticked} ticked")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_items = self.plan is not None and self.list.count() > 0
        self.tick_all_button.setEnabled(has_items)
        self.untick_all_button.setEnabled(has_items)

    def _rebuild(self) -> None:
        self.stop()
        self._updating = True
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
            self._apply_check(item)
            if path not in self.cache and path not in self._items:
                to_load.append(path)
            self._items.setdefault(path, []).append(item)
            self.list.addItem(item)
        self._updating = False
        self._refresh_count()
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

    def _shot_status(self, shot: Shot) -> str:
        """The most actionable status among the shot's files (e.g. New beats Already imported)."""
        found = {self._statuses.get(p.path, "new") for p in shot.photos}
        return next(s for s in STATUSES if s in found)

    def _set_icon(self, item: QListWidgetItem, path: Path) -> None:
        image = self.cache.get(path)
        if path not in self.cache:
            pixmap = self._loading
        elif image is None:
            pixmap = self._missing
        else:
            pixmap = QPixmap.fromImage(image)
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        item.setIcon(QIcon(_with_status(pixmap, self._shot_status(shot))))

    def _on_loaded(self, path: Path, image: QImage | None) -> None:
        self.cache[path] = image
        self._updating = True  # a new icon also reports itemChanged
        for item in self._items.get(path, []):
            self._set_icon(item, path)
        self._updating = False
        if all(p in self.cache for p in self._items):
            self.thumbnails_loaded.emit()

    def _tooltip(self, shot: Shot) -> str:
        meta = shot.primary.meta
        lines = [
            ", ".join(
                f"{p.filename} ({STATUS_LABELS[self._statuses.get(p.path, 'new')].lower()})"
                for p in shot.photos
            )
        ]
        camera = " ".join(filter(None, (meta.make, meta.model)))
        if camera:
            lines.append(camera)
        if meta.capture_time:
            day, _, clock = meta.capture_time.partition(" ")
            lines.append(f"{day.replace(':', '-')} {clock}")
        lines.append("Double-click to open")
        return "\n".join(lines)

    def _open(self, item: QListWidgetItem) -> None:
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(shot.primary.path)))
