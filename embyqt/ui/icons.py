"""播放器控制栏用的矢量图标（不依赖系统图标主题）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  # QtSvg 不可用时退回内置矢量绘制
    QSvgRenderer = None  # type: ignore[assignment]

_SIZE = 22
_COLOR = "#eef2fb"
_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
_SVG_FILES = {
    "play": "play.svg",
    "pause": "pause.svg",
    "back10": "back10.svg",
    "forward10": "forward10.svg",
    "volume": "volume.svg",
    "muted": "muted.svg",
    "audio": "audio.svg",
    "subtitle": "subtitle.svg",
    "fullscreen": "fullscreen.svg",
    "restore": "restore.svg",
    "speed": "speed.svg",
    "check": "check.svg",
    "uncheck": "uncheck.svg",
    "arrow_back": "arrow_back.svg",
    "arrow_forward": "arrow_forward.svg",
    "info": "info.svg",
    "settings": "settings.svg",
    "logout": "logout.svg",
}
_RENDERERS = {}


def _svg_icon(name: str, size: int, color: str):
    if QSvgRenderer is None:
        return None
    filename = _SVG_FILES.get(name)
    if not filename:
        return None
    path = _ASSET_DIR / filename
    if not path.is_file():
        return None

    renderer = _RENDERERS.get((filename, color))
    if renderer is None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        # Material 图标默认黑色路径，把颜色注入到 svg 根节点
        head_end = text.find(">")
        head = text[:head_end] if head_end > 0 else ""
        if "fill=" in head:
            for old in ('fill="#000000"', "fill='#000000'", 'fill="currentColor"', "fill='currentColor'"):
                text = text.replace(old, f'fill="{color}"', 1)
        else:
            text = text.replace("<svg", f'<svg fill="{color}"', 1)
        renderer = QSvgRenderer(text.encode("utf-8"))
        if not renderer.isValid():
            return None
        _RENDERERS[(filename, color)] = renderer

    scaled = size * 2
    pixmap = QPixmap(scaled, scaled)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, scaled, scaled))
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


def _speaker(p: QPainter, color: QColor) -> None:
    path = QPainterPath()
    path.moveTo(4, 9)
    path.lineTo(8, 9)
    path.lineTo(12.5, 4.5)
    path.lineTo(12.5, 19.5)
    path.lineTo(8, 15)
    path.lineTo(4, 15)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _draw(name: str, p: QPainter, color: QColor) -> None:
    pen = QPen(color, 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    if name == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon([QPointF(6, 4.5), QPointF(19, 11), QPointF(6, 17.5)])
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(6, 4.5, 3.8, 15), 1.5, 1.5)
        p.drawRoundedRect(QRectF(12.2, 4.5, 3.8, 15), 1.5, 1.5)
    elif name in ("back10", "forward10"):
        p.save()
        pen = QPen(color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 顶部留口的圆环：120°（左上）逆时针经底部到 60°（右上）
        p.drawArc(QRectF(3.8, 4.3, 14.4, 14.4), 120 * 16, 300 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        if name == "back10":
            p.drawPolygon([QPointF(2.9, 5.2), QPointF(7.7, 2.5), QPointF(8.2, 8.0)])
        else:
            p.drawPolygon([QPointF(19.1, 5.2), QPointF(14.3, 2.5), QPointF(13.8, 8.0)])
        p.restore()
        font = QFont()
        font.setPixelSize(9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(0, 6.5, _SIZE, 12), Qt.AlignmentFlag.AlignCenter, "10")
    elif name in ("volume", "muted"):
        _speaker(p, color)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(11, 8, 5, 6), -60 * 16, 120 * 16)
        if name == "muted":
            p.drawLine(QPointF(15, 9), QPointF(20, 14))
            p.drawLine(QPointF(20, 9), QPointF(15, 14))
        else:
            p.drawArc(QRectF(11, 5, 9, 12), -55 * 16, 110 * 16)
    elif name in ("fullscreen", "restore"):
        if name == "fullscreen":
            pairs = [((5, 5), (9.5, 5), (5, 9.5)), ((17, 5), (12.5, 5), (17, 9.5)),
                     ((17, 17), (12.5, 17), (17, 12.5)), ((5, 17), (9.5, 17), (5, 12.5))]
        else:
            pairs = [((9.5, 5), (5, 5), (5, 9.5)), ((12.5, 5), (17, 5), (17, 9.5)),
                     ((12.5, 17), (17, 17), (17, 12.5)), ((9.5, 17), (5, 17), (5, 12.5))]
        for a, b, c in pairs:
            p.drawLine(QPointF(*a), QPointF(*b))
            p.drawLine(QPointF(*a), QPointF(*c))
    elif name == "audio":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(5.5, 14.5, 5, 4.5))
        p.setPen(pen)
        p.drawLine(QPointF(10, 16.5), QPointF(10, 5.5))
        p.drawLine(QPointF(10, 5.5), QPointF(17, 4))
        p.drawLine(QPointF(17, 4), QPointF(17, 9))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(12.5, 13.2, 5, 4.2))
    elif name == "subtitle":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(3.5, 6, 15, 10.5), 2, 2)
        p.drawLine(QPointF(7, 10.5), QPointF(15, 10.5))
        p.drawLine(QPointF(7, 13.5), QPointF(12, 13.5))
    elif name == "check":
        pen = QPen(color, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(QPointF(4.5, 10.5), QPointF(8.2, 14.2))
        p.drawLine(QPointF(8.2, 14.2), QPointF(17.5, 5.8))
    elif name == "uncheck":
        pen = QPen(color, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(5.5, 5.5), QPointF(18.5, 18.5))
        p.drawLine(QPointF(18.5, 5.5), QPointF(5.5, 18.5))
    elif name == "arrow_back":
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(QPointF(19, 10), QPointF(5, 10))
        p.drawLine(QPointF(5, 10), QPointF(10.5, 4.5))
        p.drawLine(QPointF(5, 10), QPointF(10.5, 15.5))
    elif name == "info":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 1.6))
        p.drawRoundedRect(QRectF(3.5, 3.5, 13, 13), 1.5, 1.5)
        p.setPen(QPen(color, 2.0))
        p.drawPoint(QPointF(10, 7))
        p.drawLine(QPointF(10, 9.5), QPointF(10, 14))
    elif name == "settings":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 1.7))
        p.drawEllipse(QPointF(10, 10), 3.0, 3.0)
        p.drawEllipse(QPointF(10, 10), 7.2, 7.2)
        p.drawLine(QPointF(10, 1.5), QPointF(10, 4.0))
        p.drawLine(QPointF(10, 16), QPointF(10, 18.5))
        p.drawLine(QPointF(1.5, 10), QPointF(4.0, 10))
        p.drawLine(QPointF(16, 10), QPointF(18.5, 10))
    elif name == "logout":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 1.7))
        p.drawRoundedRect(QRectF(3.5, 4, 7.5, 12), 1.5, 1.5)
        p.drawLine(QPointF(10, 10), QPointF(18.5, 10))
        p.drawLine(QPointF(15.5, 7), QPointF(18.5, 10))
        p.drawLine(QPointF(15.5, 13), QPointF(18.5, 10))


@lru_cache(maxsize=64)
def icon(name: str, size: int = _SIZE, color: str = _COLOR) -> QIcon:
    rendered = _svg_icon(name, size, color)
    if rendered is not None:
        return rendered
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / _SIZE * 2, size / _SIZE * 2)
    _draw(name, painter, QColor(color))
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)
