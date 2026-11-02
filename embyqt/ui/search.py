"""搜索页。"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..async_task import run_async
from ..context import AppContext
from .widgets import POSTER_SPACING, EmptyState, FlowLayout, PosterCard, make_button

FILTERS = [
    ("全部", "Movie,Series,Episode,BoxSet,Video"),
    ("电影", "Movie"),
    ("剧集", "Series"),
    ("合集", "BoxSet"),
]


class SearchPage(QWidget):
    open_item = Signal(dict)
    play_item = Signal(dict)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._cards: List[PosterCard] = []
        self._include_types = FILTERS[0][1]
        self._searching = False
        self._build_ui()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(380)
        self._debounce.timeout.connect(self._run_search)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 24, 30, 0)
        root.setSpacing(16)

        self.title = QLabel("搜索")
        self.title.setObjectName("pageTitle")
        root.addWidget(self.title)

        self.input = QLineEdit()
        self.input.setPlaceholderText("搜索电影、剧集、单集…")
        self.input.setClearButtonEnabled(True)
        self.input.setMinimumHeight(42)
        self.input.textChanged.connect(lambda _t: self._debounce.start())
        self.input.returnPressed.connect(self._run_search)
        root.addWidget(self.input)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (label, types) in enumerate(FILTERS):
            button = make_button(label, "chip")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked, t=types: self._set_filter(t))
            self._group.addButton(button, index)
            chips.addWidget(button)
        chips.addStretch(1)
        root.addLayout(chips)

        self.status = QLabel("输入关键词开始搜索")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll, 1)

        self.container = QWidget()
        self.flow = FlowLayout(self.container, h_spacing=POSTER_SPACING, v_spacing=24)
        self.scroll.setWidget(self.container)

    def focus_search(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def _set_filter(self, types: str) -> None:
        self._include_types = types
        if self.input.text().strip():
            self._run_search()

    def _run_search(self) -> None:
        term = self.input.text().strip()
        if not term:
            self._clear_results()
            self.status.setText("输入关键词开始搜索")
            return
        if self._searching:
            return
        self._searching = True
        self.status.setText("搜索中…")
        run_async(
            self.ctx.client.search,
            term,
            self._include_types,
            on_done=self._on_results,
            on_error=self._on_error,
        )

    def _clear_results(self) -> None:
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

    def _on_results(self, items: List[dict]) -> None:
        self._searching = False
        self._clear_results()
        if not items:
            self.status.setText("没有找到匹配的内容")
            return
        self.status.setText(f"找到 {len(items)} 个结果")
        for item in items:
            card = PosterCard(self.ctx, item, 162)
            card.activated.connect(self.open_item)
            card.play_requested.connect(self.play_item)
            card.command.connect(self._on_command)
            self.flow.addWidget(card)
            self._cards.append(card)

    def _on_error(self, message: str) -> None:
        self._searching = False
        self.status.setText(f"搜索失败：{message}")

    def _on_command(self, action: str, item: dict) -> None:
        if action in ("played", "unplayed"):
            run_async(self.ctx.client.set_played, item["Id"], action == "played", on_done=lambda _r: self._run_search())
        elif action in ("favorite", "unfavorite"):
            run_async(self.ctx.client.set_favorite, item["Id"], action == "favorite", on_done=lambda _r: self._run_search())
