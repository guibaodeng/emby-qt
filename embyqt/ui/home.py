"""首页：焦点横幅 + 继续观看 + 各媒体库最新。"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..api import TICKS, parse_runtime
from ..async_task import run_async
from ..context import AppContext
from . import theme
from .icons import icon
from .widgets import EmptyState, PosterRow, make_button


class IconTextButton(QPushButton):
    """图标与文字严格垂直居中的按钮（避免 QPushButton 图标基线偏移）。"""

    def __init__(self, text: str, icon, icon_size: int = 20, parent=None) -> None:
        super().__init__("", parent)
        self._text = text
        self._icon = icon
        self._icon_size = icon_size
        font = self.font()
        font.setPointSize(10)
        self.setFont(font)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(text) + icon_size + 8 + 40
        self.setFixedSize(width, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._text)
        gap = 8
        total = self._icon_size + gap + text_width
        left = (self.width() - total) / 2.0
        icon_rect = QRect(
            int(left), (self.height() - self._icon_size) // 2, self._icon_size, self._icon_size
        )
        self._icon.paint(painter, icon_rect)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRect(
                int(left) + self._icon_size + gap,
                0,
                text_width,
                self.height(),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )


class HeroBanner(QWidget):
    play_requested = Signal(dict)
    details_requested = Signal(dict)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._item: Optional[dict] = None
        self._pixmap: Optional[QPixmap] = None
        self.setFixedHeight(400)
        self.setMinimumWidth(600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 0, 44, 40)
        layout.setSpacing(12)
        layout.addStretch(1)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 34px; font-weight: 800; color: #ffffff;")
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("font-size: 13px; color: #cfd6e4;")
        layout.addWidget(self.meta_label)

        self.overview_label = QLabel("")
        self.overview_label.setWordWrap(True)
        self.overview_label.setMaximumWidth(720)
        self.overview_label.setMaximumHeight(52)
        self.overview_label.setStyleSheet("font-size: 13px; color: #b9c2d3;")
        layout.addWidget(self.overview_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.play_button = make_button("▶  播放", "primary")
        self.play_button.clicked.connect(self._on_play)
        buttons.addWidget(self.play_button)
        self.details_button = IconTextButton(
            "查看详情", icon("info", 20, "#eef2fb"), 20
        )
        self.details_button.setObjectName("secondary")
        self.details_button.clicked.connect(self._on_details)
        buttons.addWidget(self.details_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    # ---- 数据 -----------------------------------------------------------
    def set_item(self, item: dict) -> None:
        self._item = item
        self.title_label.setText(item.get("Name") or "")
        self.meta_label.setText(self._meta_text(item))
        overview = (item.get("Overview") or "").strip()
        self.overview_label.setText(overview)
        self.overview_label.setVisible(bool(overview))
        self.play_button.setText(
            "▶  继续播放" if self.ctx.resume_ticks(item) and not self.ctx.is_played(item) else "▶  播放"
        )
        if item.get("Type") == "Series":
            self.play_button.setText("查看剧集")
        self._pixmap = None
        self.update()
        url = self.ctx.backdrop_url(item, 1600)
        if url:
            self.ctx.load_image(url, QSize(1600, 640), self._apply_backdrop)

    def _meta_text(self, item: dict) -> str:
        parts = []
        if item.get("ProductionYear"):
            parts.append(str(item["ProductionYear"]))
        kind = item.get("Type")
        kind_text = {
            "Movie": "电影",
            "Series": "剧集",
            "Episode": "单集",
            "BoxSet": "合集",
            "Video": "视频",
        }.get(kind, "")
        if kind_text:
            parts.append(kind_text)
        if item.get("RunTimeTicks"):
            parts.append(parse_runtime(item["RunTimeTicks"]))
        if item.get("CommunityRating"):
            parts.append(f"★ {item['CommunityRating']:.1f}")
        genres = item.get("Genres") or []
        if genres:
            parts.append(" / ".join(genres[:3]))
        return "   ·   ".join(parts)

    def _apply_backdrop(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def _on_play(self) -> None:
        if self._item is not None:
            self.play_requested.emit(self._item)

    def _on_details(self) -> None:
        if self._item is not None:
            self.details_requested.emit(self._item)

    # ---- 绘制 -----------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.setClipPath(path)
        painter.fillPath(path, QColor("#171c26"))

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(rect.toRect(), self._pixmap)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor("#1d2a3d"))
            gradient.setColorAt(1.0, QColor("#10141c"))
            painter.fillPath(path, gradient)

        horizontal = QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0.0, QColor(12, 15, 20, 245))
        horizontal.setColorAt(0.55, QColor(12, 15, 20, 170))
        horizontal.setColorAt(1.0, QColor(12, 15, 20, 40))
        painter.fillRect(rect, horizontal)

        vertical = QLinearGradient(rect.bottomLeft(), rect.topLeft())
        vertical.setColorAt(0.0, QColor(14, 17, 22, 230))
        vertical.setColorAt(0.45, QColor(14, 17, 22, 0))
        painter.fillRect(rect, vertical)
        painter.end()


class HomePage(QWidget):
    open_item = Signal(dict)
    play_item = Signal(dict)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._views: List[dict] = []
        self._latest_by_view: Dict[str, List[dict]] = {}
        self._resume: List[dict] = []
        self._rows: Dict[str, PosterRow] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(30, 26, 30, 40)
        self.content_layout.setSpacing(26)
        self.scroll.setWidget(self.content)

        self.hero = HeroBanner(ctx)
        self.hero.details_requested.connect(self.open_item)
        self.hero.play_requested.connect(self._on_hero_play)
        self.content_layout.addWidget(self.hero)

        self.status = QLabel("正在加载媒体库…")
        self.status.setObjectName("muted")
        self.content_layout.addWidget(self.status)

        self.retry_button = make_button("重试", "chip")
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(self._retry)
        self.content_layout.addWidget(self.retry_button)

        self.resume_row = PosterRow(ctx, "继续观看", card_width=190, fill=True)
        self.resume_row.activated.connect(self.open_item)
        self.resume_row.play_requested.connect(self.play_item)
        self.resume_row.setVisible(False)
        self.content_layout.addWidget(self.resume_row)

        self.content_layout.addStretch(1)
        self._loaded = False

    # ---- 加载 -----------------------------------------------------------
    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self._loaded = True
        self.status.setText("正在加载媒体库…")
        self.status.setVisible(True)
        run_async(
            self.ctx.client.get_views,
            on_done=self._on_views,
            on_error=self._on_error,
        )

    def _on_error(self, message: str) -> None:
        self.status.setText(f"加载失败：{message}（请检查网络后重试）")
        self.status.setVisible(True)
        self.retry_button.setVisible(True)

    def _retry(self) -> None:
        self.retry_button.setVisible(False)
        self.status.setText("正在重新加载…")
        self._loaded = False
        self.load(force=True)

    def _on_views(self, views: List[dict]) -> None:
        self._views = views
        self.status.setVisible(False)
        self.retry_button.setVisible(False)
        run_async(self.ctx.client.get_resume, 12, on_done=self._on_resume, on_error=lambda _m: None)
        for view in views:
            self._add_library_row(view)

    def _on_resume(self, items: List[dict]) -> None:
        self._resume = items
        if items:
            self.resume_row.set_items(items)
            self.hero.set_item(items[0])
        elif not self._latest_by_view:
            pass

    def _add_library_row(self, view: dict) -> None:
        row = PosterRow(self.ctx, f"最新 · {view.get('Name','')}", card_width=170, fill=True)
        row.activated.connect(self.open_item)
        row.play_requested.connect(self.play_item)
        row.setVisible(False)
        # 插到 resume_row 之后、stretch 之前
        index = self.content_layout.indexOf(self.resume_row) + 1
        self.content_layout.insertWidget(index + len(self._rows), row)
        self._rows[view["Id"]] = row
        view_id = view["Id"]
        run_async(
            self.ctx.client.get_latest,
            view_id,
            24,
            on_done=lambda items, vid=view_id: self._on_latest(vid, items),
            on_error=lambda _m, vid=view_id: self._rows.get(vid) and self._rows[vid].setVisible(False),
        )

    def _on_latest(self, view_id: str, items: List[dict]) -> None:
        if not items:
            return
        self._latest_by_view[view_id] = items
        row = self._rows.get(view_id)
        if row is not None:
            row.set_items(items)
        if self.hero._item is None or (
            self.hero._item.get("Type") == "Series" and not self._resume
        ):
            self.hero.set_item(items[0])

    def _on_hero_play(self, item: dict) -> None:
        if item.get("Type") == "Series":
            self.open_item.emit(item)
        else:
            self.play_item.emit(item)
