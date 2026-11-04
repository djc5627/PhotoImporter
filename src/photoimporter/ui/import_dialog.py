from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.planner import ImportBreakdown

COLUMN_LABELS = {
    "new": "New",
    "recent_deleted": "Recently deleted",
    "deleted": "Deleted",
    "older": "Probably deleted",
    "already": "Imported again",
}
LEFT_OUT_LABELS = {
    "recent_deleted": "recently deleted",
    "deleted": "deleted since import",
    "older": "probably deleted earlier",
    "already": "already imported",
}


def _photos(n: int) -> str:
    return f"{n} photo" if n == 1 else f"{n} photos"


def not_importing_text(breakdown: ImportBreakdown) -> str:
    """e.g. 'Not importing: 5 new photos you deselected, 120 already imported.'"""
    left_out = breakdown.not_importing
    parts = [f"{_photos(left_out['new']).replace(' ', ' new ', 1)} you deselected"] * bool(
        left_out["new"]
    )
    parts += [f"{left_out[s]} {label}" for s, label in LEFT_OUT_LABELS.items() if left_out[s]]
    return "Not importing: " + ", ".join(parts) + "." if parts else ""


class ImportConfirmDialog(QDialog):
    """Asks to confirm an import, showing what will be copied per camera and status."""

    def __init__(self, breakdown: ImportBreakdown, target: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Confirm import")
        layout = QVBoxLayout(self)

        files = "" if breakdown.files == breakdown.pictures else f" ({breakdown.files} files)"
        self.title_label = QLabel(f"<b>Import {_photos(breakdown.pictures)}{files}?</b>")
        title_font = self.title_label.font()
        title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)
        self.target_label = QLabel(f"Into:  {target}")
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.target_label)

        statuses = breakdown.statuses
        headers = ["Camera", "Saved to", *(COLUMN_LABELS[s] for s in statuses), "Total"]
        rows = [(c.name, c.saved_to, c.counts, c.total) for c in breakdown.cameras]
        if len(rows) > 1:
            rows.append(("Total", "", breakdown.totals, breakdown.pictures))
        self.table = QTableWidget(len(rows), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bold = QFont(self.table.font())
        bold.setBold(True)
        for r, (name, saved_to, counts, total) in enumerate(rows):
            values = [name, saved_to, *(counts[s] or "–" for s in statuses), total]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == len(values) - 1 or (len(rows) > 1 and r == len(rows) - 1):
                    item.setFont(bold)
                self.table.setItem(r, c, item)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.resizeRowsToContents()
        height = self.table.horizontalHeader().height() + sum(
            self.table.rowHeight(r) for r in range(len(rows))
        )
        self.table.setFixedHeight(height + 2 * self.table.frameWidth())
        layout.addWidget(self.table)

        self.hidden_label = QLabel(
            f"⚠ {breakdown.hidden} of these "
            f"{'photo isn’t' if breakdown.hidden == 1 else 'photos aren’t'} in the current view."
        )
        self.hidden_label.setStyleSheet("color: #a15c00")
        self.hidden_label.setVisible(breakdown.hidden > 0)
        layout.addWidget(self.hidden_label)

        self.not_importing_label = QLabel(not_importing_text(breakdown))
        self.not_importing_label.setStyleSheet("color: gray")
        self.not_importing_label.setWordWrap(True)
        self.not_importing_label.setVisible(bool(self.not_importing_label.text()))
        layout.addWidget(self.not_importing_label)

        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton("Import", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.import_button.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(min(900, max(560, self.table.horizontalHeader().length() + 40)))
