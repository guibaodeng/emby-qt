"""应用图标（用 QPainter 生成，避免依赖外部资源）。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap, QPolygonF
from PySide6.QtCore import QPointF

from . import theme


_WHALE_ICON = Path(__file__).resolve().parent.parent / "assets" / "whaleplayer.png"


def app_icon(size: int = 256) -> QIcon:
    if _WHALE_ICON.is_file():
        return QIcon(str(_WHALE_ICON))
    # 资源缺失时的绿色占位图标
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(0, 0, size, size)
    path = QPainterPath()
    path.addRoundedRect(rect.adjusted(2, 2, -2, -2), size * 0.22, size * 0.22)
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#2f8cff"))
    gradient.setColorAt(1.0, QColor("#0b4a94"))
    painter.fillPath(path, gradient)

    play = QPolygonF(
        [
            QPointF(size * 0.40, size * 0.30),
            QPointF(size * 0.40, size * 0.70),
            QPointF(size * 0.72, size * 0.50),
        ]
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawPolygon(play)
    painter.end()
    return QIcon(pixmap)
