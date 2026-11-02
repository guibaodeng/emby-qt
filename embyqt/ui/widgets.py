"""通用 UI 组件：流式布局、海报卡片、横向列表、剧集行等。"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..api import TICKS, format_ticks, parse_runtime
from ..context import AppContext
from . import theme
from .icons import icon


# ---------------------------------------------------------------------------
# 布局辅助
# ---------------------------------------------------------------------------
POSTER_SPACING = 24


class FlowLayout(QLayout):
    """自动换行的流式布局，用于海报网格。"""

    def __init__(self, parent: Optional[QWidget] = None, h_spacing: int = POSTER_SPACING, v_spacing: int = 24) -> None:
        super().__init__(parent)
        self._items: List = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def __del__(self) -> None:  # pragma: no cover - Qt 清理
        while self._items:
            self._items.pop()

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        space_x = self._h
        space_y = self._v

        for item in self._items:
            widget = item.widget()
            if widget is None or widget.isHidden():
                continue
            item_size = item.sizeHint()
            next_x = x + item_size.width() + space_x
            if next_x - space_x > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item_size.width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            line_height = max(line_height, item_size.height())
        return y + line_height - rect.y() + margins.bottom()


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


# ---------------------------------------------------------------------------
# 基础控件
# ---------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """单行省略文本。"""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._full = text
        super().setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._apply()

    def text(self) -> str:  # noqa: D401
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width() - 2))
        super().setText(elided)


class Chip(QLabel):
    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("metaChip")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


def make_button(text: str, kind: str = "", parent: Optional[QWidget] = None) -> QPushButton:
    button = QPushButton(text, parent)
    if kind:
        button.setObjectName(kind)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class SectionHeader(QWidget):
    link_clicked = Signal()

    def __init__(self, title: str, link_text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._title = QLabel(title)
        self._title.setObjectName("sectionTitle")
        layout.addWidget(self._title)
        layout.addStretch(1)
        self._link = None
        if link_text:
            self._link = make_button(link_text, "link")
            self._link.clicked.connect(self.link_clicked)
            layout.addWidget(self._link)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_link_text(self, text: str) -> None:
        if self._link is not None:
            self._link.setText(text)


class EmptyState(QWidget):
    def __init__(self, text: str, sub: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 48, 0, 48)
        layout.setSpacing(8)
        heading = QLabel(text)
        heading.setObjectName("emptyHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        if sub:
            detail = QLabel(sub)
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail.setObjectName("muted")
            layout.addWidget(detail)


# ---------------------------------------------------------------------------
# 海报图与卡片
# ---------------------------------------------------------------------------
class PosterImage(QWidget):
    clicked = Signal()
    double_clicked = Signal()

    def __init__(
        self,
        ctx: AppContext,
        width: int = 170,
        height: int = 255,
        radius: int = 10,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._radius = radius
        self._pixmap = None
        self._url = ""
        self._hover = False
        self._progress = 0.0
        self._played = False
        self._requested = False
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_item(self, item: dict, url: Optional[str] = None) -> None:
        self._url = url if url is not None else self.ctx.poster_url(item)
        self._progress = self.ctx.progress_fraction(item)
        self._played = self.ctx.is_played(item)
        self._pixmap = None
        self._requested = False
        self.update()

    def _request_if_needed(self) -> None:
        """只在真正绘制（可见）时才请求图片，避免一次拉几百张。"""
        if self._requested or self._pixmap is not None or not self._url:
            return
        self._requested = True
        QTimer.singleShot(0, self._load)

    def load_now(self) -> None:
        """立即加载（用于详情页海报等首屏关键图片）。"""
        if not self._url:
            return
        self._requested = True
        self._load()

    def _load(self) -> None:
        if not self._url:
            return
        size = QSize(self.width(), self.height())
        url = self._url

        def apply(pixmap) -> None:
            if self._url != url:
                return
            self._pixmap = pixmap
            self.update()

        self.ctx.load_image(url, size, apply, radius=self._radius)

    def set_image(self, pixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def set_card_size(self, width: int, height: int) -> None:
        """窗口宽度变化时同步海报尺寸；已加载的图清空，按新尺寸重新取。"""
        width = max(2, int(width))
        height = max(2, int(height))
        if self.width() == width and self.height() == height:
            return
        self.setFixedSize(width, height)
        if self._pixmap is not None:
            self._pixmap = None
            self._requested = False
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._request_if_needed()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(rect.toRect(), self._pixmap)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor(theme.PLACEHOLDER_1))
            gradient.setColorAt(1.0, QColor(theme.PLACEHOLDER_2))
            painter.fillPath(path, gradient)
            painter.setPen(QColor(theme.PLACEHOLDER_TEXT))
            font = QFont(self.font())
            font.setPointSize(9)
            font.setBold(True)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "EMBY")

        if self._hover:
            painter.fillPath(path, QColor(255, 255, 255, 18))
        if self._progress > 0 and not self._played:
            bar_height = 4.0
            bar_top = rect.height() - bar_height
            painter.fillRect(QRectF(0, bar_top, rect.width(), bar_height), QColor(0, 0, 0, 160))
            painter.fillRect(
                QRectF(0, bar_top, rect.width() * min(1.0, self._progress), bar_height),
                theme.ACCENT_COLOR,
            )
        if self._played:
            diameter = 22.0
            badge = QRectF(rect.width() - diameter - 8, 8, diameter, diameter)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(82, 181, 75, 235))
            painter.drawRoundedRect(badge, diameter / 2, diameter / 2)
            painter.setPen(QColor("#0b1a0c"))
            font = QFont(self.font())
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "✓")

        painter.setClipping(False)
        if self._hover:
            pen = QPen(QColor(theme.ACCENT))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self._radius, self._radius)


class PosterCard(QWidget):
    activated = Signal(dict)
    play_requested = Signal(dict)
    command = Signal(str, dict)

    def __init__(self, ctx: AppContext, item: dict, width: int = 170, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self._width = width
        self.setFixedWidth(width)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.image = PosterImage(ctx, width, int(round(width * 1.5)), 10)
        self.image.set_item(item)
        layout.addWidget(self.image)

        self.title_label = ElidedLabel(item.get("Name", "未知"))
        self.title_label.setObjectName("posterTitle")
        layout.addWidget(self.title_label)

        meta = self._meta_text(item)
        self.meta_label = ElidedLabel(meta)
        self.meta_label.setObjectName("posterMeta")
        layout.addWidget(self.meta_label)

        self.image.clicked.connect(self._on_click)
        self.image.double_clicked.connect(lambda: self.play_requested.emit(self.item))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.image.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image.customContextMenuRequested.connect(
            lambda pos: self._on_context_menu(self.image.mapTo(self, pos))
        )

    def set_card_width(self, width: int) -> None:
        width = max(80, int(width))
        if width == self._width:
            return
        self._width = width
        self.setFixedWidth(width)
        self.image.set_card_size(width, int(round(width * 1.5)))
        self.updateGeometry()

    def _meta_text(self, item: dict) -> str:
        parts = []
        year = item.get("ProductionYear")
        if year:
            parts.append(str(year))
        rating = item.get("CommunityRating")
        if rating:
            parts.append(f"★ {rating:.1f}")
        runtime = item.get("RunTimeTicks")
        if runtime and item.get("Type") in ("Movie", "Episode"):
            parts.append(parse_runtime(runtime))
        if not parts:
            kind = item.get("Type") or ""
            return {"Series": "剧集", "Movie": "电影", "Episode": "单集"}.get(kind, "")
        return " · ".join(parts)

    def _on_click(self) -> None:
        self.activated.emit(self.item)

    def _on_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("▶  播放", lambda: self.play_requested.emit(self.item))
        detail_action = menu.addAction("查看详情", lambda: self.activated.emit(self.item))
        detail_action.setIcon(icon("info", 16, theme.TEXT))
        menu.addSeparator()
        played = bool((self.item.get("UserData") or {}).get("Played"))
        menu.addAction(
            "标记为未看" if played else "标记为已看",
            lambda: self.command.emit("unplayed" if played else "played", self.item),
        )
        favorite = bool((self.item.get("UserData") or {}).get("IsFavorite"))
        menu.addAction(
            "取消收藏" if favorite else "加入收藏",
            lambda: self.command.emit("unfavorite" if favorite else "favorite", self.item),
        )
        menu.exec(self.mapToGlobal(pos))

    def _set_hover(self, hovered: bool) -> None:
        self.title_label.setProperty("hovered", hovered)
        style = self.title_label.style()
        style.unpolish(self.title_label)
        style.polish(self.title_label)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._set_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)
        super().leaveEvent(event)


_WHEEL_MODE = "page"


def set_wheel_mode(mode: str) -> None:
    """设置鼠标滚轮在横向列表上的行为：page（页面上下）或 row（分类左右）。"""
    global _WHEEL_MODE
    _WHEEL_MODE = "row" if str(mode).lower() == "row" else "page"


class HScrollArea(QScrollArea):
    """横向滚动区域。

    - page 模式：普通垂直滚轮交还外层页面，Shift+滚轮/横向手势滚分类；
    - row 模式：普通垂直滚轮直接滚分类。
    """

    # 横向滚动速度（滚轮一格约 120 单位）
    WHEEL_FACTOR = 3.0
    PIXEL_FACTOR = 2.0

    def wheelEvent(self, event) -> None:  # noqa: N802
        bar = self.horizontalScrollBar()
        if bar.maximum() <= 0:
            event.ignore()
            return

        pixel = event.pixelDelta()
        angle = event.angleDelta()
        if pixel.x() or pixel.y():
            delta_x, delta_y = pixel.x(), pixel.y()
            factor = self.PIXEL_FACTOR
        else:
            delta_x, delta_y = angle.x(), angle.y()
            factor = self.WHEEL_FACTOR
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if delta_x and not shift:
            bar.setValue(bar.value() - int(delta_x * factor))
            event.accept()
            return
        if shift and delta_y:
            bar.setValue(bar.value() - int(delta_y * factor))
            event.accept()
            return
        if _WHEEL_MODE == "row" and delta_y:
            bar.setValue(bar.value() - int(delta_y * factor))
            event.accept()
            return

        # page 模式：垂直滚轮不消费，交给外层 QScrollArea 上下滚动
        event.ignore()


class RowNavButton(QPushButton):
    """横向列表的左右翻页按钮，使用 SVG 图标保证几何居中。"""

    def __init__(self, icon_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__("", parent)
        self._icon_name = icon_name
        self._hovered = False
        self.setFixedSize(44, 44)
        self.setIconSize(QSize(20, 20))
        theme.signals.changed.connect(self._refresh_icon)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        color = theme.ON_ACCENT if self._hovered else theme.TEXT
        self.setIcon(icon(self._icon_name, 20, color))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._refresh_icon()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._refresh_icon()
        super().leaveEvent(event)


class PosterRow(QWidget):
    """带标题的横向海报列表。

    ``fill=True`` 时会根据可用宽度自动放大卡片，尽量把一行铺满；
    条目不足以铺满时居中显示，避免宽屏右侧留下大片空白。
    """

    activated = Signal(dict)
    play_requested = Signal(dict)
    link_clicked = Signal()

    def __init__(
        self,
        ctx: AppContext,
        title: str,
        items: Optional[List[dict]] = None,
        card_width: int = 170,
        link_text: str = "",
        fill: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._fill = fill
        self._base_width = card_width
        self._card_width = card_width
        self._spacing = POSTER_SPACING
        self._max_width = 280
        self._items: List[dict] = []
        self._cards: List[PosterCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.header = SectionHeader(title, link_text)
        self.header.link_clicked.connect(self.link_clicked)
        layout.addWidget(self.header)

        self.scroll = HScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(int(card_width * 1.5) + 52)
        self._content = QWidget()
        self._row = QHBoxLayout(self._content)
        self._row.setContentsMargins(0, 0, 8, 0)
        self._row.setSpacing(self._spacing)
        self.scroll.setWidget(self._content)
        layout.addWidget(self.scroll)

        self.nav_left = RowNavButton("arrow_back", self.scroll)
        self.nav_right = RowNavButton("arrow_forward", self.scroll)
        for button, direction, tip in (
            (self.nav_left, -1, "向左"),
            (self.nav_right, 1, "向右"),
        ):
            button.setObjectName("rowNav")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{tip}浏览")
            button.clicked.connect(lambda _checked=False, d=direction: self._scroll_by(d))
            button.hide()
        self.scroll.horizontalScrollBar().valueChanged.connect(self._update_nav)
        self.scroll.horizontalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._update_nav()
        )
        self._nav_anim = QPropertyAnimation(
            self.scroll.horizontalScrollBar(), b"value", self
        )
        self._nav_anim.setDuration(240)
        self._nav_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.setInterval(150)
        self._fill_timer.timeout.connect(self._apply_fill)

        if items:
            self.set_items(items)

    # ---- 数据 -----------------------------------------------------------
    def set_items(self, items: List[dict]) -> None:
        self._items = list(items)
        self._card_width = self._base_width
        self._rebuild()
        if self._fill:
            QTimer.singleShot(0, self._apply_fill)

    def items(self) -> List[dict]:
        return list(self._items)

    # ---- 布局 -----------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_nav()
        self._update_nav()
        if self._fill and self._items:
            self._fill_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._place_nav)
        QTimer.singleShot(0, self._update_nav)

    def _place_nav(self) -> None:
        if not hasattr(self, "nav_left"):
            return
        size = self.nav_left.width()
        # 以海报图片区域（不含标题/简介）为基准垂直居中
        poster_height = int(self._card_width * 1.5)
        top = max(0, (poster_height - size) // 2)
        self.nav_left.move(8, top)
        self.nav_right.move(max(8, self.scroll.width() - size - 8), top)
        self.nav_left.raise_()
        self.nav_right.raise_()

    def _update_nav(self) -> None:
        if not hasattr(self, "nav_left"):
            return
        bar = self.scroll.horizontalScrollBar()
        can_scroll = bar.maximum() > 0 and bool(self._items)
        left = can_scroll and bar.value() > 0
        right = can_scroll and bar.value() < bar.maximum()
        self.nav_left.setVisible(left)
        self.nav_right.setVisible(right)
        self.nav_left.setEnabled(left)
        self.nav_right.setEnabled(right)

    def _scroll_by(self, direction: int) -> None:
        bar = self.scroll.horizontalScrollBar()
        if bar.maximum() <= 0:
            return
        step = max(260, int(self.scroll.viewport().width() * 0.8))
        target = max(0, min(bar.maximum(), bar.value() + direction * step))
        self._nav_anim.stop()
        self._nav_anim.setStartValue(bar.value())
        self._nav_anim.setEndValue(target)
        self._nav_anim.start()

    def _rebuild(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()

        self._row.addStretch(1)
        for item in self._items:
            card = PosterCard(self.ctx, item, self._card_width)
            card.activated.connect(self.activated)
            card.play_requested.connect(self.play_requested)
            self._row.addWidget(card)
            self._cards.append(card)
        self._row.addStretch(1)

        self.scroll.setFixedHeight(int(self._card_width * 1.5) + 52)
        self.setVisible(bool(self._items))
        self._place_nav()
        self._update_nav()

    def _apply_fill(self) -> None:
        if not self._fill or not self._items:
            return
        available = self.scroll.viewport().width() - 12
        if available < 80:
            return
        count = len(self._items)
        needed = count * self._base_width + (count - 1) * self._spacing
        width = self._base_width
        if needed < available:
            width = int((available - (count - 1) * self._spacing) / count)
            width = max(self._base_width, min(width, self._max_width))
        if abs(width - self._card_width) < 6:
            return
        self._card_width = width
        self._rebuild()


# ---------------------------------------------------------------------------
# 演职人员
# ---------------------------------------------------------------------------
class PersonCard(QWidget):
    def __init__(self, ctx: AppContext, person: dict, size: int = 88, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._size = size
        self._requested = False
        self.setFixedWidth(size + 16)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.avatar = QLabel()
        self.avatar.setFixedSize(size, size)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)

        name = ElidedLabel(person.get("Name", ""))
        name.setObjectName("personName")
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(name)

        role = ElidedLabel(person.get("Role") or person.get("Type") or "")
        role.setObjectName("personRole")
        role.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(role)

        person_id = person.get("Id", "")
        self._url = ctx.person_url(person_id, 180) if person_id else ""

    def _request_if_needed(self) -> None:
        if self._requested or not self._url:
            return
        self._requested = True
        QTimer.singleShot(0, self._load)

    def _load(self) -> None:
        self.ctx.load_image(
            self._url,
            QSize(self._size, self._size),
            self._apply,
            radius=self._size // 2,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        self._request_if_needed()
        super().paintEvent(event)

    def _apply(self, pixmap) -> None:
        self.avatar.setPixmap(pixmap)


class PersonRow(QWidget):
    def __init__(self, ctx: AppContext, people: List[dict], limit: int = 14, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = HScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(152)
        layout.addWidget(self.scroll)

        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(14)
        for person in people[:limit]:
            row.addWidget(PersonCard(ctx, person))
        row.addStretch(1)
        self.scroll.setWidget(content)


# ---------------------------------------------------------------------------
# 剧集行
# ---------------------------------------------------------------------------
class EpisodeRow(QWidget):
    play_requested = Signal(dict)

    def __init__(self, ctx: AppContext, item: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._thumb_requested = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 14, 8)
        layout.setSpacing(14)

        own_tag = (item.get("ImageTags") or {}).get("Primary")
        self._thumb_size = QSize(150, 84) if own_tag else QSize(58, 84)
        self.thumb = QLabel()
        self.thumb.setFixedSize(self._thumb_size)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setObjectName("episodeThumb")
        layout.addWidget(self.thumb)
        if own_tag:
            self._thumb_url = ctx.client.image(
                item.get("Id", ""), "Primary", tag=own_tag, max_width=320
            )
        else:
            # 没有单集剧照时用集数占位，避免重复拉取同一张剧集海报
            self._thumb_url = ""
            self.thumb.setText(f"E{item.get('IndexNumber') or '?'}")

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        text_col.addStretch(1)
        title = QLabel(self._title_text(item))
        title.setObjectName("episodeTitle")
        text_col.addWidget(title)

        overview_text = (item.get("Overview") or "").strip()
        if overview_text:
            overview = QLabel(overview_text)
            overview.setWordWrap(True)
            overview.setMaximumHeight(36)
            overview.setObjectName("episodeOverview")
            text_col.addWidget(overview)

        info_parts = []
        runtime = item.get("RunTimeTicks")
        if runtime:
            info_parts.append(parse_runtime(runtime))
        premiere = item.get("PremiereDate")
        if premiere:
            info_parts.append(str(premiere)[:10])
        progress = self.ctx.progress_fraction(item)
        if progress > 0 and not self.ctx.is_played(item):
            runtime_ticks = int(item.get("RunTimeTicks") or 0)
            info_parts.append(
                f"已看至 {format_ticks(self.ctx.resume_ticks(item))} / {format_ticks(runtime_ticks)}"
            )
        if self.ctx.is_played(item):
            info_parts.append("✓ 已看完")
        if info_parts:
            info = QLabel("  ·  ".join(info_parts))
            info.setObjectName("episodeInfo")
            text_col.addWidget(info)

        text_col.addStretch(1)
        layout.addLayout(text_col, 1)

    @staticmethod
    def _title_text(item: dict) -> str:
        index = item.get("IndexNumber")
        name = (item.get("Name") or "").strip()
        label = f"第 {index} 集" if index else name
        if index and name and name != label and not name.startswith("第 "):
            return f"{label} · {name}"
        return label or "未命名"

    def _request_thumb(self) -> None:
        if self._thumb_requested or not self._thumb_url:
            return
        self._thumb_requested = True
        QTimer.singleShot(0, self._load_thumb)

    def _load_thumb(self) -> None:
        self.ctx.load_image(
            self._thumb_url, self._thumb_size, self._apply_thumb, radius=6
        )

    def _apply_thumb(self, pixmap) -> None:
        self.thumb.setPixmap(pixmap)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_requested.emit(self.item)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._request_thumb()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 8.0
        if self._hover:
            painter.setPen(QPen(QColor(theme.ROW_BORDER), 1))
            painter.setBrush(QColor(theme.ROW_HOVER))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ROW_BG))
        painter.drawRoundedRect(rect, radius, radius)

        progress = self.ctx.progress_fraction(self.item)
        if progress > 0 and not self.ctx.is_played(self.item):
            bar_rect = QRectF(10, rect.height() - 3, (rect.width() - 22) * progress, 2.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.ACCENT_COLOR)
            painter.drawRoundedRect(bar_rect, 1.2, 1.2)
