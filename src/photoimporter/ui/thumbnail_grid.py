from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEvent,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..core.models import PhotoFile
from ..core.planner import STATUS_LABELS, STATUSES, CameraGroup, ImportPlan
from ..core.thumbnails import Shot, Thumbnail, ThumbnailSource, group_shots
from .theme import accent, colors, current_surfaces, icon, muted, set_icon

# Tile sizes for the size slider. Large uses the cameras' bigger embedded preview.
SIZES = [("Small", QSize(120, 90)), ("Medium", QSize(160, 120)), ("Large", QSize(320, 240))]
DEFAULT_SIZE = 1
SMALL_IMAGE = QSize(160, 120)  # what the camera's small thumbnail gives
LARGE_IMAGE = QSize(384, 288)  # room for Large tiles stretched to fill the row
TILE_PADDING = QSize(28, 44)  # around the image: the border and the file name


def _is_large(size: QSize) -> bool:
    return size.width() > SMALL_IMAGE.width()


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


# Formats embedded previews come in. Naming the format matters: without one, Qt asks every
# image plugin to guess, and the SVG plugin's guess connects Qt signals, which needs a lock
# the main thread may hold while waiting for Python's GIL that this (worker) thread holds:
# a deadlock that froze thumbnail loading now and then.
_PREVIEW_FORMATS = ("JPG", "TIFF", "PNG")


def _reader(device_or_path: QBuffer | str, fmt: str) -> QImageReader:
    reader = QImageReader(device_or_path, fmt.encode())
    reader.setAutoDetectImageFormat(False)  # never fall back to asking every plugin
    return reader


def _decode(data: bytes) -> QImage:
    for fmt in _PREVIEW_FORMATS:
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QBuffer.OpenModeFlag.ReadOnly)
        image = _reader(buffer, fmt).read()
        if not image.isNull():
            return image
    return QImage()


def thumbnail_image(thumb: Thumbnail, path: Path, size: QSize = SMALL_IMAGE) -> QImage | None:
    """Decode, rotate upright and shrink a thumbnail to fit `size`.

    Falls back to decoding a JPG itself when it has no embedded preview, or (for a large
    size) only one too small to look sharp.
    """
    image = _decode(thumb.data) if thumb.data else QImage()
    small = not image.isNull() and max(image.width(), image.height()) < size.width() * 0.8
    if (image.isNull() or small) and path.suffix.lower() in (".jpg", ".jpeg"):
        reader = _reader(str(path), "jpg")
        reader.setAutoTransform(True)  # the file's own orientation is applied here
        full = reader.size()
        if full.isValid():
            reader.setScaledSize(full.scaled(size * 2, Qt.AspectRatioMode.KeepAspectRatio))
        decoded = reader.read()
        if not decoded.isNull():
            image, thumb = decoded, Thumbnail(None, 1)
    if image.isNull():
        return None
    angle = _ROTATIONS.get(thumb.orientation)
    if angle:
        image = image.transformed(QTransform().rotate(angle))
    return image.scaled(
        size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


class _JobSignals(QObject):
    loaded = Signal(object, object)  # path, QImage or None
    finished = Signal()


class ThumbnailJob(QRunnable):
    """Loads thumbnails for `paths` in small batches, so the first ones appear quickly."""

    def __init__(
        self,
        paths: Sequence[Path],
        source_factory: Callable[[], ThumbnailSource],
        large: bool = False,
    ):
        super().__init__()
        self.paths = list(paths)
        self.large = large
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
                thumbs = source.extract(batch, large=self.large) if source else {}
            except Exception:
                thumbs = {}
            for path in batch:
                if self.cancel.is_set():
                    return
                image = thumbnail_image(
                    thumbs.get(path, Thumbnail(None)),
                    path,
                    LARGE_IMAGE if self.large else SMALL_IMAGE,
                )
                self.signals.loaded.emit(path, image)
            start += size
            size = 120


def _placeholder(text: str, size: QSize) -> QPixmap:
    pixmap = QPixmap(size)
    pixmap.fill(QColor(colors().placeholder_bg))
    painter = QPainter(pixmap)
    painter.setPen(QColor(colors().placeholder_text))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def _with_status(pixmap: QPixmap, status: str, size: QSize) -> QPixmap:
    """The thumbnail, shrunk to fit `size`, with its status as a label in the top-left corner."""
    fits = pixmap.size().scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
    if pixmap.size() != fits:  # tiles stretch a little to fill the row
        pixmap = pixmap.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    result = QPixmap(size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    left = (size.width() - pixmap.width()) // 2
    top = (size.height() - pixmap.height()) // 2
    clip = QPainterPath()  # rounded corners on the photo
    clip.addRoundedRect(QRectF(left, top, pixmap.width(), pixmap.height()), 8, 8)
    painter.setClipPath(clip)
    painter.drawPixmap(left, top, pixmap)
    painter.setClipping(False)
    font = painter.font()
    font.setPointSizeF(max(font.pointSizeF() - 1, 7))
    font.setBold(True)
    painter.setFont(font)
    text = STATUS_LABELS[status]
    width = painter.fontMetrics().horizontalAdvance(text) + 10
    height = painter.fontMetrics().height() + 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(STATUS_COLORS[status]))
    x, y = left + 6, top + 6  # a pill on the photo's corner
    painter.drawRoundedRect(QRectF(x, y, width + 4, height), height / 2, height / 2)
    painter.setPen(QColor("white"))
    painter.drawText(x, y, width + 4, height, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return result


CHOSEN_ROLE = Qt.ItemDataRole.UserRole + 1  # "on", "off" or "part" (some files of the shot)
HEADER_HEIGHT = 34


@dataclass
class DayHeader:
    """The row above one day's photos; its UserRole data in the list."""

    day: date | None  # None: photos without a usable date
    shots: list[Shot]
    counts: str = ""  # e.g. "84 photos · 12 selected", kept up to date by the grid

    @property
    def title(self) -> str:
        if self.day is None:
            return "Unknown date"
        return f"{self.day:%A}, {self.day:%B} {self.day.day}, {self.day.year}"


def shot_day(shot: Shot) -> date | None:
    """The day a shot was taken (from its capture time, else the file date)."""
    try:
        return datetime.strptime(shot.sort_time[:10], "%Y:%m:%d").date()
    except ValueError:
        return None


def is_header(item: QListWidgetItem) -> bool:
    return isinstance(item.data(Qt.ItemDataRole.UserRole), DayHeader)


def _item_photos(item: QListWidgetItem) -> list[PhotoFile]:
    """The files a tile or a day header stands for."""
    data = item.data(Qt.ItemDataRole.UserRole)
    if isinstance(data, DayHeader):
        return [p for shot in data.shots for p in shot.photos]
    return data.photos


class _TileDelegate(QStyledItemDelegate):
    """Draws chosen tiles with a coloured border and the others dimmed."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        header = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(header, DayHeader):
            self._paint_header(painter, option, header, index.data(CHOSEN_ROLE) or "off")
            return
        chosen = index.data(CHOSEN_ROLE) or "off"
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        # Unselected photos are dimmed, a little less under the mouse.
        dim = (0.7 if hover else 0.45) if chosen == "off" else 1.0
        card = QRectF(option.rect).adjusted(4, 4, -4, -4)
        surfaces = current_surfaces()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(surfaces.line), 1) if hover else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(surfaces.field_hover if hover else surfaces.tile))
        painter.setOpacity(dim)
        painter.drawRoundedRect(card, 12, 12)
        painter.restore()
        opt = QStyleOptionViewItem(option)
        opt.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_HasFocus
            | QStyle.StateFlag.State_MouseOver  # drawn above, as the card
        )
        painter.save()
        painter.setOpacity(dim)
        super().paint(painter, opt, index)
        painter.restore()
        if chosen != "off":
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(accent(), 3)
            if chosen == "part":
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(1.5, 1.5, -1.5, -1.5), 11, 11)
            painter.restore()
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.save()
            painter.setPen(QPen(QColor(colors().focus), 1, Qt.PenStyle.DotLine))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()

    @staticmethod
    def _paint_header(
        painter: QPainter, option: QStyleOptionViewItem, header: DayHeader, chosen: str
    ) -> None:
        """A day's title and counts, after a round tick that selects the whole day."""
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The tick: filled when the whole day is selected, a dash when part of it is.
        box = QRectF(rect.x() + 6, rect.center().y() - 8, 16, 16)
        if chosen == "off":
            painter.setPen(QPen(QColor(colors().tick_border), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(box)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent())
            painter.drawEllipse(box)
            painter.setPen(QPen(QColor("white"), 2))
            c = box.center()
            if chosen == "on":
                painter.drawPolyline([c + QPointF(-4, 0), c + QPointF(-1, 3), c + QPointF(4, -3)])
            else:
                painter.drawLine(c + QPointF(-4, 0), c + QPointF(4, 0))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 1)
        painter.setFont(font)
        painter.setPen(option.palette.text().color())
        text_rect = rect.adjusted(32, 0, -8, 0)
        painter.drawText(
            text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), header.title
        )
        title_width = painter.fontMetrics().horizontalAdvance(header.title)
        font.setBold(False)
        font.setPointSizeF(font.pointSizeF() - 1)
        painter.setFont(font)
        painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(
            text_rect.adjusted(title_width + 12, 0, 0, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            header.counts,
        )
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
    size_changed = Signal(int)  # index into SIZES

    def __init__(
        self, source_factory: Callable[[], ThumbnailSource], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.source_factory = source_factory
        self.plan: ImportPlan | None = None
        self.groups: list[CameraGroup] = []
        # Decoded thumbnails, small and large kept apart so switching sizes back is instant.
        self.cache: dict[Path, QImage | None] = {}
        self.large_cache: dict[Path, QImage | None] = {}
        self.size_index = DEFAULT_SIZE
        self._tile = SIZES[DEFAULT_SIZE][1]  # the image area of each tile, after fitting
        self._cell = self._tile + TILE_PADDING  # a whole tile, image plus border and name
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(40)
        self._fit_timer.timeout.connect(self._fit)
        self._statuses: dict[Path, str] = {}
        self._items: dict[Path, list[QListWidgetItem]] = {}
        self._job: ThumbnailJob | None = None
        self._running: set[ThumbnailJob] = set()  # kept alive until their thread is done
        self._anchor: int | None = None  # row of the last clicked tile, for Shift-click
        self._last_toggle: tuple[int, set[Path]] | None = None  # to undo on double-click

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = self.toolbar = QHBoxLayout()  # the window adds its own controls here too
        self.show_label = QLabel("Show:")
        row.addWidget(self.show_label)
        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self._rebuild)
        row.addWidget(self.view_combo)
        self.count_label = QLabel()
        muted(self.count_label)
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setToolTip("Select every photo shown (Ctrl+A)")
        self.select_all_button.clicked.connect(lambda: self._choose_shown(True))
        self.select_none_button = QPushButton("Select none")
        self.select_none_button.setToolTip("Deselect every photo shown")
        self.select_none_button.clicked.connect(lambda: self._choose_shown(False))
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setToolTip("Delete the selected photos shown from the SD card (Delete)")
        self.delete_button.clicked.connect(self.delete_requested)
        for button, name in (
            (self.select_all_button, "square-check"),
            (self.select_none_button, "square"),
            (self.delete_button, "trash-2"),
        ):
            set_icon(button, name)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(0, len(SIZES) - 1)
        self.size_slider.setPageStep(1)
        self.size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.size_slider.setFixedWidth(70)
        self.size_slider.setValue(DEFAULT_SIZE)
        self.size_slider.valueChanged.connect(self.set_thumbnail_size)
        self.size_label = QLabel()
        self.size_label.setMinimumWidth(QLabel("Medium").sizeHint().width())
        size_icon = QLabel()
        size_icon.setToolTip("Thumbnail size")
        size_icon.setPixmap(icon("zoom-in").pixmap(16, 16))
        self._size_icon = size_icon
        # [Show] [camera, added by the window] Select all, none, Delete … count … size
        for button in (self.select_all_button, self.select_none_button, self.delete_button):
            row.addWidget(button)
        row.addWidget(self.count_label)
        row.addStretch(1)
        row.addWidget(size_icon)
        row.addWidget(self.size_slider)
        row.addWidget(self.size_label)
        layout.addLayout(row)

        self.list = QListWidget()
        self.list.setObjectName("thumbnails")
        self.list.setMouseTracking(True)  # for the hover highlight
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        # Tiles and full-width day headers share the list, so sizes aren't uniform and there
        # is no grid: each item's size hint places it.
        self.list.setUniformItemSizes(False)
        self.list.setSpacing(0)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setItemDelegate(_TileDelegate(self.list))
        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.installEventFilter(self)
        self.list.viewport().installEventFilter(self)  # Ctrl+scroll and resizes arrive here
        # Always there, so it appearing doesn't change the width and the columns.
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        panel = QFrame()
        panel.setObjectName("panel")  # a rounded panel behind the thumbnails
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 4, 4, 10)
        panel_layout.addWidget(self.list)
        panel_layout.addWidget(self._build_empty_view())
        layout.addWidget(panel)
        self._apply_size()
        self._refresh_buttons()

    # Public

    def set_plan(self, plan: ImportPlan | None, groups: list[CameraGroup] | None = None) -> None:
        """Show `plan`, limited to `groups` (all cameras if None or empty)."""
        if plan is None or (self.plan is not None and plan.source != self.plan.source):
            self.cache.clear()
            self.large_cache.clear()
        if plan is not self.plan:
            self.view_combo.blockSignals(True)
            self.view_combo.setCurrentIndex(0)
            self.view_combo.blockSignals(False)
        self._statuses = plan.statuses() if plan else {}
        self.plan = plan
        self.groups = list(groups or (plan.groups if plan else []))
        self._refresh_combo()
        self._refresh_empty_view()
        self._rebuild()

    def _build_empty_view(self) -> QWidget:
        """What the grid shows before a card is chosen, or when it has no photos."""
        self.empty_view = QWidget()
        outer = QVBoxLayout(self.empty_view)
        outer.addStretch(1)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = QLabel()
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text = muted(QLabel())
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text.setWordWrap(True)
        self.empty_button = QPushButton("Choose a folder…")
        set_icon(self.empty_button, "folder-open")
        for widget in (self.empty_icon, self.empty_title, self.empty_text):
            outer.addWidget(widget)
        outer.addSpacing(8)
        outer.addWidget(self.empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(2)
        self._refresh_empty_view()
        return self.empty_view

    def _refresh_empty_view(self) -> None:
        empty_card = self.plan is not None and not self.plan.photos()
        self.empty_view.setVisible(self.plan is None or empty_card)
        self.list.setVisible(not self.empty_view.isVisibleTo(self))
        if empty_card:
            self.empty_title.setText("No photos on this card")
            self.empty_text.setText("There are no JPG or RAW files on it.")
        else:
            self.empty_title.setText("Insert an SD card")
            self.empty_text.setText(
                "Photo Importer shows what's on it and which photos\naren't in your library yet."
            )
        self.empty_button.setVisible(not empty_card)
        self.empty_icon.setPixmap(icon("hard-drive", 44, current_surfaces().muted).pixmap(44, 44))

    @property
    def nominal_size(self) -> QSize:
        """The image size chosen with the slider."""
        return SIZES[self.size_index][1]

    @property
    def thumb_size(self) -> QSize:
        """The image size actually shown: the chosen one, stretched or shrunk to fill rows."""
        return self._tile

    def set_thumbnail_size(self, index: int) -> None:
        """Show tiles at SIZES[index]: 0 small, 1 medium, 2 large."""
        index = max(0, min(index, len(SIZES) - 1))
        if index == self.size_index:
            return
        large_before = _is_large(self.nominal_size)
        self.size_index = index
        self._apply_size()
        if _is_large(self.nominal_size) != large_before:
            self._rebuild()  # loads the other kind of preview
        self.size_changed.emit(index)

    def _apply_size(self) -> None:
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(self.size_index)
        self.size_slider.blockSignals(False)
        name = SIZES[self.size_index][0]
        self.size_label.setText(name)
        self.size_slider.setToolTip(f"Thumbnail size: {name} (Ctrl+scroll over the photos)")
        self._fit(force=True)

    def columns_for(self, width: int) -> int:
        """Columns that fill `width`: as many whole tiles as fit, plus one more if at least
        half of it would; the tiles are then resized so the columns fill the row exactly."""
        cell = self.nominal_size.width() + TILE_PADDING.width()
        return max(1, int(width / cell + 0.5))

    def _fit(self, force: bool = False) -> None:
        """Size the tiles so whole columns fill the grid's width, and headers span it."""
        nominal = self.nominal_size
        width = self.list.viewport().width()
        # A few pixels spare: Qt wraps a tile that would end exactly at the edge.
        image_width = max((width - 4) // self.columns_for(width) - TILE_PADDING.width(), 40)
        tile = QSize(image_width, round(image_width * nominal.height() / nominal.width()))
        changed = tile != self._tile or force
        if changed:
            self._tile = tile
            self._cell = tile + TILE_PADDING
            self._loading = _placeholder("Loading…", tile)
            self._missing = _placeholder("No preview", tile)
            self.list.setIconSize(tile)
        for item in self._all_items():
            if is_header(item):
                item.setSizeHint(self._header_size())
            elif changed:
                item.setSizeHint(self._cell)
                self._set_icon(item, item.data(Qt.ItemDataRole.UserRole).primary.path)

    def _header_size(self) -> QSize:
        return QSize(max(self.list.viewport().width() - 4, 100), HEADER_HEIGHT)

    def _all_items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count())]

    def tiles(self) -> list[QListWidgetItem]:
        """The photo tiles shown, without the day headers."""
        return [item for item in self._all_items() if not is_header(item)]

    def headers(self) -> list[QListWidgetItem]:
        return [item for item in self._all_items() if is_header(item)]

    @property
    def cell_size(self) -> QSize:
        return self._cell

    def _cache(self) -> dict[Path, QImage | None]:
        return self.large_cache if _is_large(self.nominal_size) else self.cache

    def refresh_checks(self) -> None:
        """Update highlights and counts after the plan's selection changed elsewhere."""
        for item in self._all_items():
            self._apply_chosen(item)
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
            for item in self.tiles()
            for p in item.data(Qt.ItemDataRole.UserRole).photos
            if self.plan.is_selected(p)
        ]

    def stop(self) -> None:
        if self._job is not None:
            self._job.cancel.set()
            self._job = None

    def shots(self) -> list[Shot]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.tiles()]

    def item_for(self, name: str) -> QListWidgetItem:
        for item in self.tiles():
            if item.data(Qt.ItemDataRole.UserRole).name == name:
                return item
        raise KeyError(name)

    def header_for(self, title: str) -> QListWidgetItem:
        for item in self.headers():
            if item.data(Qt.ItemDataRole.UserRole).title == title:
                return item
        raise KeyError(title)

    def click(self, item: QListWidgetItem, shift: bool = False) -> None:
        """Toggle a tile, or with `shift` choose the range from the last clicked tile.

        Clicking a day header selects every photo from that day, or deselects them if all
        already are.
        """
        if self.plan is None:
            return
        row = self.list.row(item)
        if is_header(item):
            self._choose([item], item.data(CHOSEN_ROLE) != "on")
            self._last_toggle = None
            self.list.setCurrentItem(item)
            return
        if shift and self._anchor is not None and self._anchor < self.list.count():
            low, high = sorted((self._anchor, row))
            between = [self.list.item(r) for r in range(low, high + 1)]
            self._choose([i for i in between if not is_header(i)], True)
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
        data = item.data(Qt.ItemDataRole.UserRole)
        photos = _item_photos(item)
        chosen = sum(self.plan.is_selected(p) for p in photos) if self.plan else 0
        state = "off" if chosen == 0 else "on" if chosen == len(photos) else "part"
        if isinstance(data, DayHeader):
            picked = sum(
                any(self.plan.is_selected(p) for p in shot.photos) if self.plan else False
                for shot in data.shots
            )
            total = len(data.shots)
            data.counts = f"{total} photo{'s' if total != 1 else ''} · {picked} selected"
            item.setData(Qt.ItemDataRole.UserRole, data)
        item.setData(CHOSEN_ROLE, state)

    def _choose(self, items: list[QListWidgetItem], on: bool) -> None:
        if self.plan is None:
            return
        for item in items:
            self.plan.select(_item_photos(item), on)
        self.refresh_checks()
        self.selection_changed.emit()

    def _choose_shown(self, on: bool) -> None:
        self._choose(self.tiles(), on)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.click(item, shift)

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        # The first click of a double-click toggled the tile; put it back, then open the photo.
        if is_header(item):
            return
        row = self.list.row(item)
        if self.plan is not None and self._last_toggle and self._last_toggle[0] == row:
            photos = item.data(Qt.ItemDataRole.UserRole).photos
            self.plan.select(photos, False)
            self.plan.select([p for p in photos if p.path in self._last_toggle[1]], True)
            self._last_toggle = None
            self.refresh_checks()
            self.selection_changed.emit()
        self._open(item)

    def restyle(self) -> None:
        """Redraw for a new light/dark palette (placeholder tiles have their own colours)."""
        self._size_icon.setPixmap(icon("zoom-in").pixmap(16, 16))
        self._refresh_empty_view()
        self._fit(force=True)
        self.list.viewport().update()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt name)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.restyle()
        super().changeEvent(event)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.list.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_timer.start()  # once resizing pauses, not on every pixel
        if (
            obj is self.list.viewport()
            and event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            step = 1 if event.angleDelta().y() > 0 else -1 if event.angleDelta().y() < 0 else 0
            self.set_thumbnail_size(self.size_index + step)
            return True
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
            tiles = self.tiles()
            chosen = sum(item.data(CHOSEN_ROLE) != "off" for item in tiles)
            self.count_label.setText(f"{len(tiles)} pictures, {chosen} selected")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_items = self.plan is not None and bool(self.tiles())
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
        cache = self._cache()
        for day, day_shots in groupby(shots, key=shot_day):  # shots are newest first
            day_shots = list(day_shots)
            header = QListWidgetItem()
            header.setData(Qt.ItemDataRole.UserRole, DayHeader(day, day_shots))
            header.setToolTip("Click to select or deselect every photo from this day")
            header.setSizeHint(self._header_size())
            self._apply_chosen(header)
            self.list.addItem(header)
            for shot in day_shots:
                self._add_tile(shot, cache, to_load)
        self._refresh_count()
        self._start_loading(to_load)

    def _add_tile(self, shot: Shot, cache: dict[Path, QImage | None], to_load: list[Path]) -> None:
        item = QListWidgetItem(f"{shot.name}  {shot.badge}".strip())
        item.setData(Qt.ItemDataRole.UserRole, shot)
        item.setToolTip(self._tooltip(shot))
        item.setSizeHint(self._cell)
        path = shot.primary.path
        self._set_icon(item, path)
        self._apply_chosen(item)
        if path not in cache and path not in self._items:
            to_load.append(path)
        self._items.setdefault(path, []).append(item)
        self.list.addItem(item)

    def _start_loading(self, to_load: list[Path]) -> None:
        if to_load:
            large = _is_large(self.nominal_size)
            job = ThumbnailJob(to_load, self.source_factory, large)
            job.setAutoDelete(False)
            job.signals.loaded.connect(
                lambda path, image, large=large: self._on_loaded(path, image, large)
            )
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
        cache = self._cache()
        image = cache.get(path)
        if path not in cache:
            pixmap = self._loading
        elif image is None:
            pixmap = self._missing
        else:
            pixmap = QPixmap.fromImage(image)
        shot: Shot = item.data(Qt.ItemDataRole.UserRole)
        item.setIcon(QIcon(_with_status(pixmap, self._shot_status(shot), self.thumb_size)))

    def _on_loaded(self, path: Path, image: QImage | None, large: bool = False) -> None:
        (self.large_cache if large else self.cache)[path] = image
        if large != _is_large(self.nominal_size):
            return  # the size changed since this was asked for
        for item in self._items.get(path, []):
            self._set_icon(item, path)
        if all(p in self._cache() for p in self._items):
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
