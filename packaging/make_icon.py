"""Draw the app icon: an SD card with a small landscape photo on it.

Run with `uv run python packaging/make_icon.py` to regenerate
src/photoimporter/ui/icon.png and packaging/icon.ico.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPolygonF,
)

ROOT = Path(__file__).resolve().parent.parent


def draw(size: int = 256) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)

    # Background tile
    tile = QLinearGradient(QPointF(0, 0), QPointF(0, 256))
    tile.setColorAt(0, QColor("#3b82c4"))
    tile.setColorAt(1, QColor("#1e4f86"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(tile)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)

    # SD card with a clipped corner
    card = QPolygonF(
        [QPointF(70, 38), QPointF(164, 38), QPointF(196, 70), QPointF(196, 218), QPointF(70, 218)]
    )
    path = QPainterPath()
    path.addPolygon(card)
    path.closeSubpath()
    p.setBrush(QColor("#f4f6f8"))
    p.drawPath(path)

    # Contacts
    p.setBrush(QColor("#c9a227"))
    for i in range(4):
        p.drawRoundedRect(QRectF(88 + i * 22, 50, 14, 30), 3, 3)

    # Photo: sky, sun and hills
    photo = QRectF(84, 104, 98, 96)
    clip = QPainterPath()
    clip.addRoundedRect(photo, 8, 8)
    p.setClipPath(clip)
    sky = QLinearGradient(photo.topLeft(), photo.bottomLeft())
    sky.setColorAt(0, QColor("#ffcf70"))
    sky.setColorAt(1, QColor("#f08a4b"))
    p.fillRect(photo, sky)
    p.setBrush(QColor("#fff3c4"))
    p.drawEllipse(QPointF(156, 130), 12, 12)
    p.setBrush(QColor("#2f6b4f"))
    p.drawEllipse(QPointF(100, 212), 70, 46)
    p.setBrush(QColor("#1f4d39"))
    p.drawEllipse(QPointF(176, 222), 60, 46)
    p.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)
    image = draw()
    image.save(str(ROOT / "src" / "photoimporter" / "ui" / "icon.png"))
    image.save(str(ROOT / "packaging" / "icon.ico"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
