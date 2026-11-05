"""The "This import" panel's rows: one per kind of photo on the card."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import icon, muted


class CategoryRow(QFrame):
    """An icon chip, a count and a label, with a line below; clicking shows those photos.

    `switch`, if given, is the row's own on/off control (e.g. to include deleted photos).
    """

    clicked = Signal()

    def __init__(
        self,
        icon_name: str,
        label: str,
        switch: QCheckBox | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("categoryRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_name = icon_name
        self.switch = switch
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 10, 6)
        row.setSpacing(10)
        self.chip = QLabel()
        self.chip.setObjectName("chip")
        self.chip.setFixedSize(QSize(34, 34))
        self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.chip)

        text = QVBoxLayout()
        text.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.number = QLabel("0")
        self.number.setObjectName("rowNumber")
        self.label = QLabel(label)
        self.label.setObjectName("rowLabel")
        top.addWidget(self.number)
        top.addWidget(self.label)
        top.addStretch(1)
        self.sub = muted(QLabel())
        self.sub.setObjectName("rowSub")
        text.addLayout(top)
        text.addWidget(self.sub)
        row.addLayout(text, stretch=1)
        if switch is not None:
            switch.setObjectName("switch")
            switch.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(switch)
        self.set_active(False)

    def set_values(self, number: int, sub: str) -> None:
        self.number.setText(str(number))
        self.sub.setText(sub)

    def set_active(self, active: bool) -> None:
        """Highlight the row whose photos the grid shows."""
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.restyle()

    def restyle(self) -> None:
        """Redraw the chip's icon for the current palette and highlight."""
        color = (
            self.palette().color(self.palette().ColorRole.Highlight)
            if self.property("active")
            else None
        )
        self.chip.setPixmap(icon(self.icon_name, 16, color).pixmap(16, 16))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
