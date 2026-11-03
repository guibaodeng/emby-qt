"""媒体库浏览页：海报网格 + 排序 + 类型筛选 + 滚动加载。"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..async_task import run_async
from ..context import AppContext
from . import theme
from .icons import icon
from .widgets import POSTER_SPACING, EmptyState, FlowLayout, PosterCard, RoundedComboBox, make_button

PAGE_SIZE = 60

INCLUDE_TYPES = {
    "movies": "Movie",
    "tvshows": "Series",
    "music": "MusicAlbum",
    "boxsets": "BoxSet",
    "homevideos": "Video",
    "musicvideos": "MusicVideo",
    "books": "Book",
}

SORT_OPTIONS = [
    ("按名称", "SortName"),
    ("最近添加", "DateCreated"),
    ("发行年份", "ProductionYear"),
    ("评分", "CommunityRating"),
    ("随机", "Random"),
]


class SortOrderButton(QPushButton):
    """排序按钮：图标与文字行内居中，固定 4px 间距。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("", parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(84)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(4)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addStretch(1)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.text_label = QLabel("")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

    def set_state(self, icon_name: str, text: str) -> None:
        self.icon_label.setPixmap(icon(icon_name, 16, theme.TEXT).pixmap(16, 16))
        self.text_label.setText(text)
        self.text_label.setStyleSheet(
            f"color: {theme.TEXT}; background: transparent; font-size: 13px;"
        )


class LibraryPage(QWidget):
    open_item = Signal(dict)
    play_item = Signal(dict)

    def __init__(
        self,
        ctx: AppContext,
        view: dict,
        parent: Optional[QWidget] = None,
        *,
        filters: str = "",
        include_types: str = "",
        show_genre: bool = True,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.view = view
        self.view_id = str(view.get("Id", ""))
        self.collection_type = view.get("CollectionType") or ""
        self._filters = filters
        self._show_genre = show_genre
        self._include_types = include_types or INCLUDE_TYPES.get(
            self.collection_type, "Movie,Series,Episode,Video"
        )

        self._start = 0
        self._total = 0
        self._loading = False
        self._finished = False
        self._items: List[dict] = []
        self._cards: List[PosterCard] = []
        self._card_width = 162
        self._sort_by = "SortName" if self.collection_type not in ("movies", "tvshows") else "DateCreated"
        self._sort_order = "Descending" if self._sort_by == "DateCreated" else "Ascending"
        self._genre = ""

        self._build_ui()
        self.load(force=True)

    # ---- UI -------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        # 右侧不留页面边距，让竖向滚动条贴到窗口右缘
        root.setContentsMargins(30, 24, 0, 0)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 30, 0)
        header.setSpacing(14)
        self.title_label = QLabel(self.view.get("Name", "媒体库"))
        self.title_label.setObjectName("pageTitle")
        header.addWidget(self.title_label)
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        self.count_label.setStyleSheet("font-size: 12px;")
        header.addWidget(self.count_label)
        header.addStretch(1)

        self.genre_combo = None
        if self._show_genre:
            self.genre_combo = RoundedComboBox()
            self.genre_combo.setMinimumWidth(130)
            self.genre_combo.addItem("全部类型", "")
            self.genre_combo.currentIndexChanged.connect(self._on_genre_changed)
            header.addWidget(self.genre_combo)

        self.sort_combo = RoundedComboBox()
        self.sort_combo.setMinimumWidth(120)
        for label, value in SORT_OPTIONS:
            self.sort_combo.addItem(label, value)
        index = max(0, [v for _l, v in SORT_OPTIONS].index(self._sort_by))
        self.sort_combo.setCurrentIndex(index)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header.addWidget(self.sort_combo)

        self.order_button = SortOrderButton()
        self.order_button.setToolTip("切换排序方向")
        self.order_button.clicked.connect(self._toggle_order)
        header.addWidget(self.order_button)
        self._update_order_button()
        theme.signals.changed.connect(self._update_order_button)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: QTimer.singleShot(0, self._update_card_width)
        )
        self.scroll.viewport().installEventFilter(self)
        root.addWidget(self.scroll, 1)

        self.container = QWidget()
        self.flow = FlowLayout(self.container, h_spacing=POSTER_SPACING, v_spacing=24)
        # 滚动条贴窗口边，卡片仍保留 30px 右侧呼吸空间
        self.flow.setContentsMargins(0, 0, 30, 0)
        self.scroll.setWidget(self.container)

        self.footer = QLabel("")
        self.footer.setObjectName("muted")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.footer.setStyleSheet("font-size: 12px; padding: 16px;")
        root.addWidget(self.footer)

    # ---- 数据 -----------------------------------------------------------
    def load(self, force: bool = False) -> None:
        if self._loading:
            return
        if force:
            self._start = 0
            self._finished = False
            self._items = []
            for card in self._cards:
                card.setParent(None)
                card.deleteLater()
            self._cards.clear()
            while self.flow.count():
                item = self.flow.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
        if self._finished:
            return
        self._loading = True
        self.footer.setText("正在加载…")
        run_async(
            self.ctx.client.get_items,
            parent_id=self.view_id,
            include_types=self._include_types,
            start=self._start,
            limit=PAGE_SIZE,
            sort_by=self._sort_by,
            sort_order=self._sort_order,
            genres=self._genre,
            filters=self._filters,
            fields="ProductionYear,RunTimeTicks,CommunityRating,ImageTags,BackdropImageTags,UserData",
            on_done=self._on_page,
            on_error=self._on_error,
        )
        if self.genre_combo is not None and not self.genre_combo.count() > 1:
            self._load_genres()

    def _on_page(self, data: dict) -> None:
        self._loading = False
        items = data.get("Items", [])
        self._total = int(data.get("TotalRecordCount") or 0)
        self._start += len(items)
        if not items:
            self._finished = True
        self._items.extend(items)
        for item in items:
            self._add_card(item)
        QTimer.singleShot(0, self._update_card_width)
        self.count_label.setText(f"共 {self._total} 项")
        self.footer.setText(
            "已经到底了" if self._finished or self._start >= self._total else f"已加载 {self._start} / {self._total}"
        )
        if not self._items:
            self.footer.setText("这个媒体库里还没有内容")
        elif self._start < self._total:
            QTimer.singleShot(80, self._fill_viewport)

    def _fill_viewport(self) -> None:
        """内容不足一屏时继续加载，避免无法滚动。"""
        if self._finished or self._loading:
            return
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() <= 0:
            self.load()

    def _on_error(self, message: str) -> None:
        self._loading = False
        self.footer.setText(f"加载失败：{message}")

    def _add_card(self, item: dict) -> None:
        card = PosterCard(self.ctx, item, self._card_width)
        card.activated.connect(self.open_item)
        card.play_requested.connect(self.play_item)
        card.command.connect(self._on_command)
        self.flow.addWidget(card)
        self._cards.append(card)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._update_card_width)
        # 页面首次挂到 QStackedWidget 时，最终 viewport 尺寸可能晚一拍才确定
        QTimer.singleShot(120, self._update_card_width)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._update_card_width)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_card_width()

    def _update_card_width(self) -> None:
        """按可用宽度计算列数，把卡片略微放大以填满整行，消除右侧空档。"""
        margins = self.flow.contentsMargins()
        available = self.scroll.viewport().width() - margins.left() - margins.right()
        if available < 120:
            return
        spacing = POSTER_SPACING
        base = 162
        columns = max(1, (available + spacing) // (base + spacing))
        target = int((available - (columns - 1) * spacing) / columns)
        target = max(base, min(230, target))
        if target == self._card_width:
            return
        self._card_width = target
        for card in self._cards:
            card.set_card_width(target)
        self.flow.invalidate()
        self.container.updateGeometry()

    def _on_command(self, action: str, item: dict) -> None:
        def done(_result=None) -> None:
            item.setdefault("UserData", {})
            if action == "played":
                item["UserData"]["Played"] = True
            elif action == "unplayed":
                item["UserData"]["Played"] = False
            elif action == "favorite":
                item["UserData"]["IsFavorite"] = True
            elif action == "unfavorite":
                item["UserData"]["IsFavorite"] = False
            self.load(force=True)

        try:
            if action in ("played", "unplayed"):
                run_async(self.ctx.client.set_played, item["Id"], action == "played", on_done=done)
            elif action in ("favorite", "unfavorite"):
                run_async(self.ctx.client.set_favorite, item["Id"], action == "favorite", on_done=done)
        except Exception:  # noqa: BLE001
            pass

    def _load_genres(self) -> None:
        run_async(
            self.ctx.client.get_genres,
            self.view_id,
            on_done=self._on_genres,
            on_error=lambda _m: None,
        )

    def _on_genres(self, genres: List[dict]) -> None:
        if not genres or self.genre_combo is None:
            return
        self.genre_combo.blockSignals(True)
        for genre in genres:
            name = genre.get("Name", "")
            if name:
                self.genre_combo.addItem(name, name)
        self.genre_combo.blockSignals(False)

    # ---- 交互 -----------------------------------------------------------
    def _on_scroll(self, value: int) -> None:
        bar = self.scroll.verticalScrollBar()
        if value >= bar.maximum() - 500:
            self.load()

    def _on_genre_changed(self, _index: int) -> None:
        if self.genre_combo is None:
            return
        self._genre = self.genre_combo.currentData() or ""
        self.load(force=True)

    def _on_sort_changed(self, _index: int) -> None:
        self._sort_by = self.sort_combo.currentData() or "SortName"
        self.load(force=True)

    def _update_order_button(self) -> None:
        ascending = self._sort_order == "Ascending"
        self.order_button.set_state(
            "arrow_up" if ascending else "arrow_down",
            "升序" if ascending else "降序",
        )

    def _toggle_order(self) -> None:
        self._sort_order = "Ascending" if self._sort_order == "Descending" else "Descending"
        self._update_order_button()
        self.load(force=True)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
