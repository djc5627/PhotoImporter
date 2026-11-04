from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
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
    ("Selected for import", lambda plan, g: plan.to_copy(g)),
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


CHOSEN_ROLE = Qt.ItemDataRole.UserRole + 1  # "on", "off" or "part" (some files of the shot)
ACCENT = QColor("#1e88e5")


class _TileDelegate(QStyledItemDelegate):
    """Draws chosen tiles with a coloured border and the others dimmed."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        chosen = index.data(CHOSEN_ROLE) or "off"
        opt = QStyleOptionViewItem(option)
        opt.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus)
        painter.save()
        if chosen == "off":
            painter.setOpacity(0.45)
        super().paint(painter, opt, index)
        painter.restore()
        if chosen != "off":
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(ACCENT, 4)
            if chosen == "part":
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(option.rect).adjusted(3, 3, -3, -3), 6, 6)
            painter.restore()
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.save()
            painter.setPen(QPen(QColor("#888"), 1, Qt.PenStyle.DotLine))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()


class ThumbnailGrid(QWidget):
    """Thumbnails of a plan's photos, one tile per shot. Highlighted tiles are chosen.

    Clicking a tile toggles it; Shift-click chooses every tile from the last clicked one.
    Choosing a tile chooses all of the shot's files (a RAW+JPG pair together). Import copies
    chosen photos; Delete removes the chosen photos shown from the card.
    """

    thumbnails_loaded = Signal()
    selection_changed = Signal()
    delete_requested = Signal()

    def __init__(
        self, source_factory: Callable[[], ThumbnailSource], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.source_factory = source_factory
        self.plan: ImportPlan | None = None
        self.groups: list[CameraGroup] = []
        self.cache: dict[Path, QImage | None] = {}
        self._statuses: dict[Path, str] = {}
        self._items: dict[Path, list[QListWidgetItem]] = {}
        self._job: ThumbnailJob | None = None
        self._running: set[ThumbnailJob] = set()  # kept alive until their thread is done
        self._anchor: int | None = None  # row of the last clicked tile, for Shift-click
        self._last_toggle: tuple[int, set[Path]] | None = None  # to undo on double-click
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
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setToolTip("Select every photo shown (Ctrl+A)")
        self.select_all_button.clicked.connect(lambda: self._choose_shown(True))
        self.select_none_button = QPushButton("Select none")
        self.select_none_button.setToolTip("Deselect every photo shown")
        self.select_none_button.clicked.connect(lambda: self._choose_shown(False))
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setToolTip("Delete the selected photos shown from the SD card (Delete)")
        self.delete_button.clicked.connect(self.delete_requested)
        for button in (self.select_all_button, self.select_none_button, self.delete_button):
            row.addWidget(button)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(THUMB_SIZE)
        self.list.setGridSize(QSize(THUMB_SIZE.width() + 20, THUMB_SIZE.height() + 40))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setItemDelegate(_TileDelegate(self.list))
        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
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

    def refresh_checks(self) -> None:
        """Update highlights and counts after the plan's selection changed elsewhere."""
        for i in range(self.list.count()):
            self._apply_chosen(self.list.item(i))
        self._refresh_combo()
        if self._view_label() == "Selected for import":
            self._rebuild()
        else:
            self._refresh_count()

    def chosen_shown(self) -> list[PhotoFile]:
        """Files of the chosen tiles currently shown (what Delete acts on)."""
        if self.plan is None:
            return []
        return [
            p
            for i in range(self.list.count())
            for p in self.list.item(i).data(Qt.ItemDataRole.UserRole).photos
            if self.plan.is_selected(p)
        ]

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

    def click(self, item: QListWidgetItem, shift: bool = False) -> None:
        """Toggle a tile, or with `shift` choose the range from the last clicked tile."""
        if self.plan is None:
            return
        row = self.list.row(item)
        if shift and self._anchor is not None and self._anchor < self.list.count():
            low, high = sorted((self._anchor, row))
            self._choose([self.list.item(r) for r in range(low, high + 1)], True)
            self._last_toggle = None
        else:
            photos = item.data(Qt.ItemDataRole.UserRole).photos
            before = {p.path for p in photos if self.plan.is_selected(p)}
            self._choose([item], item.data(CHOSEN_ROLE) != "on")
            self._last_toggle = (row, before)
        self._anchor = row
        self.list.setCurrentItem(item)

    # Choosing

    def _apply_chosen(self, item: QListWidgetItem) -> None:
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        chosen = sum(self.plan.is_selected(p) for p in shot.photos) if self.plan else 0
        state = "off" if chosen == 0 else "on" if chosen == len(shot.photos) else "part"
        item.setData(CHOSEN_ROLE, state)

    def _choose(self, items: list[QListWidgetItem], on: bool) -> None:
        if self.plan is None:
            return
        for item in items:
            self.plan.select(item.data(Qt.ItemDataRole.UserRole).photos, on)
        self.refresh_checks()
        self.selection_changed.emit()

    def _choose_shown(self, on: bool) -> None:
        self._choose([self.list.item(i) for i in range(self.list.count())], on)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.click(item, shift)

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        # The first click of a double-click toggled the tile; put it back, then open the photo.
        row = self.list.row(item)
        if self.plan is not None and self._last_toggle and self._last_toggle[0] == row:
            photos = item.data(Qt.ItemDataRole.UserRole).photos
            self.plan.select(photos, False)
            self.plan.select([p for p in photos if p.path in self._last_toggle[1]], True)
            self._last_toggle = None
            self.refresh_checks()
            self.selection_changed.emit()
        self._open(item)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.list and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Space and self.list.currentItem() is not None:
                self.click(self.list.currentItem())
                return True
            if key == Qt.Key.Key_Delete:
                self.delete_requested.emit()
                return True
            if key == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._choose_shown(True)
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
        else:
            chosen = sum(
                self.list.item(i).data(CHOSEN_ROLE) != "off" for i in range(self.list.count())
            )
            self.count_label.setText(f"{self.list.count()} pictures, {chosen} selected")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_items = self.plan is not None and self.list.count() > 0
        self.select_all_button.setEnabled(has_items)
        self.select_none_button.setEnabled(has_items)
        self.delete_button.setEnabled(bool(self.chosen_shown()))

    def _rebuild(self) -> None:
        self.stop()
        self.list.clear()
        self._items.clear()
        self._anchor = self._last_toggle = None
        shots = group_shots(self._photos(max(self.view_combo.currentIndex(), 0)))
        to_load: list[Path] = []
        for shot in shots:
            item = QListWidgetItem(f"{shot.name}  {shot.badge}".strip())
            item.setData(Qt.ItemDataRole.UserRole, shot)
            item.setToolTip(self._tooltip(shot))
            item.setSizeHint(self.list.gridSize())
            path = shot.primary.path
            self._set_icon(item, path)
            self._apply_chosen(item)
            if path not in self.cache and path not in self._items:
                to_load.append(path)
            self._items.setdefault(path, []).append(item)
            self.list.addItem(item)
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
        for item in self._items.get(path, []):
            self._set_icon(item, path)
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
        lines.append("Click to select, Shift-click to select a range, double-click to open")
        return "\n".join(lines)

    def _open(self, item: QListWidgetItem) -> None:
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(shot.primary.path)))
