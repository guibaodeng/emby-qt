"""详情页：影片 / 剧集 / 合集。"""

from __future__ import annotations

import html
import math
from typing import List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..api import parse_runtime
from ..async_task import run_async
from ..context import AppContext
from . import theme
from .icons import icon
from .widgets import (
    Chip,
    RoundedComboBox,
    ElidedLabel,
    EpisodeRow,
    EmptyState,
    PersonRow,
    PosterImage,
    PosterRow,
    SectionHeader,
    clear_layout,
    make_button,
)


def _kind_text(item: dict) -> str:
    return {
        "Movie": "电影",
        "Series": "剧集",
        "Episode": "单集",
        "BoxSet": "合集",
        "Season": "季",
        "Video": "视频",
        "MusicAlbum": "专辑",
    }.get(item.get("Type", ""), item.get("Type", ""))


def _resolution(streams: List[dict]) -> str:
    for stream in streams:
        if stream.get("Type") == "Video" and stream.get("Height"):
            height = int(stream["Height"])
            if height >= 2000:
                return "4K"
            if height >= 1000:
                return "1080p"
            if height >= 700:
                return "720p"
            return f"{height}p"
    return ""


def _audio_summary(streams: List[dict]) -> str:
    for stream in streams:
        if stream.get("Type") == "Audio":
            codec = (stream.get("Codec") or "").upper()
            channels = stream.get("Channels")
            layout = {1: "单声道", 2: "立体声", 6: "5.1", 8: "7.1"}.get(channels, "")
            if stream.get("ChannelLayout"):
                layout = stream["ChannelLayout"]
            return " ".join(part for part in (codec, layout) if part)
    return ""


def media_chips(source: dict) -> List[str]:
    if not source:
        return []
    streams = source.get("MediaStreams") or []
    chips: List[str] = []
    if source.get("Container"):
        chips.append(source["Container"].upper())
    resolution = _resolution(streams)
    if resolution:
        chips.append(resolution)
    audio = _audio_summary(streams)
    if audio:
        chips.append(audio)
    subtitles = [s for s in streams if s.get("Type") == "Subtitle"]
    if subtitles:
        chips.append(f"字幕 {len(subtitles)}")
    size = source.get("Size")
    if size:
        chips.append(f"{size / (1024 ** 3):.1f} GB")
    return chips


def source_label(source: dict) -> str:
    """把媒体源格式化成「4K · HEVC · 18.2 Mbps · 12.4 GB」。"""
    streams = source.get("MediaStreams") or []
    resolution = _resolution(streams) or "未知分辨率"
    codec = ""
    for stream in streams:
        if stream.get("Type") == "Video" and stream.get("Codec"):
            codec = str(stream["Codec"]).upper()
            break
    parts = [resolution]
    if codec:
        parts.append(codec)
    bitrate = source.get("Bitrate")
    if bitrate:
        parts.append(f"{int(bitrate) / 1_000_000:.1f} Mbps")
    size = source.get("Size")
    if size:
        parts.append(f"{int(size) / (1024 ** 3):.1f} GB")
    return " · ".join(parts)


class DetailHeader(QWidget):
    play_requested = Signal(object)   # start ticks；PySide int 仅 32 位，ticks 可能溢出
    favorite_requested = Signal()
    played_requested = Signal()
    back_requested = Signal()
    version_changed = Signal(str)

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._item: Optional[dict] = None
        self._sources: List[dict] = []
        self._backdrop: Optional[QPixmap] = None
        self.setFixedHeight(520)
        self.setMinimumWidth(760)

        self.poster = PosterImage(ctx, 200, 300, 12)
        self.poster.setParent(self)

        self.back_button = make_button("返回", "secondary")
        self.back_button.setIcon(icon("arrow_back", 18, "#eef2fb"))
        self.back_button.setIconSize(QSize(18, 18))
        self.back_button.setParent(self)
        self.back_button.clicked.connect(self.back_requested)

        self.panel = QWidget(self)
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)

        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 30px; font-weight: 800; color: #ffffff;")
        panel_layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("font-size: 13px; color: #c2cada;")
        panel_layout.addWidget(self.meta_label)

        self.chips_widget = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_widget)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(8)
        self.chips_layout.addStretch(1)
        # 详情页头部始终是深色背景，浅色主题下也使用浅色 chip 文字
        self.chips_widget.setStyleSheet(
            "QLabel#metaChip {"
            " color: #e7ecf5;"
            " background: rgba(255, 255, 255, 0.14);"
            "}"
        )
        panel_layout.addWidget(self.chips_widget)

        self.overview_label = QLabel("")
        self.overview_label.setWordWrap(True)
        self.overview_label.setTextFormat(Qt.TextFormat.RichText)
        self.overview_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.overview_label.setMaximumWidth(760)
        self.overview_label.setMaximumHeight(132)
        self.overview_label.setStyleSheet("font-size: 13px; color: #b3bccd;")
        panel_layout.addWidget(self.overview_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.version_label = QLabel("版本")
        self.version_label.setObjectName("muted")
        self.version_label.setVisible(False)
        buttons.addWidget(self.version_label)
        self.version_combo = RoundedComboBox()
        self.version_combo.setMinimumWidth(230)
        self.version_combo.setVisible(False)
        self.version_combo.currentIndexChanged.connect(self._on_version_changed)
        buttons.addWidget(self.version_combo)

        self.play_button = make_button("▶  播放", "primary")
        self.play_button.clicked.connect(lambda: self.play_requested.emit(0))
        buttons.addWidget(self.play_button)

        self.resume_button = make_button("继续播放", "secondary")
        self.resume_button.clicked.connect(self._resume)
        self.resume_button.setVisible(False)
        buttons.addWidget(self.resume_button)

        self.favorite_button = make_button("☆ 收藏", "secondary")
        self.favorite_button.clicked.connect(self.favorite_requested)
        buttons.addWidget(self.favorite_button)

        self.played_button = make_button("标记已看", "secondary")
        self.played_button.setIcon(icon("check", 18, "#eef2fb"))
        self.played_button.setIconSize(QSize(18, 18))
        self.played_button.clicked.connect(self.played_requested)
        buttons.addWidget(self.played_button)
        buttons.addStretch(1)
        panel_layout.addLayout(buttons)
        panel_layout.addStretch(1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.back_button.move(30, 22)
        self.poster.move(36, 196)
        top = 176
        width = max(320, self.width() - 36 * 2 - 200 - 36)
        self.panel.setGeometry(36 + 200 + 36, top, width, 320)

    def set_item(self, item: dict) -> None:
        self._item = item
        self.title_label.setText(item.get("Name", ""))
        self.meta_label.setText(self._meta_text(item))
        overview = (item.get("Overview") or "").strip()
        if overview:
            escaped = html.escape(overview).replace("\n", "<br>")
            self.overview_label.setText(
                f'<div style="margin:0; line-height:150%;">{escaped}</div>'
            )
        else:
            self.overview_label.clear()
        self.overview_label.setVisible(bool(overview))

        previous_source = self.current_source_id()
        self._sources = item.get("MediaSources") or []
        self._populate_versions(previous_source)
        self._refresh_chips()

        user_data = item.get("UserData") or {}
        favorite = bool(user_data.get("IsFavorite"))
        self.favorite_button.setText("★ 已收藏" if favorite else "☆ 收藏")
        played = bool(user_data.get("Played"))
        self.played_button.setText("标记未看" if played else "标记已看")
        self.played_button.setIcon(
            icon("uncheck" if played else "check", 18, "#eef2fb")
        )

        resume = int(user_data.get("PlaybackPositionTicks") or 0)
        self.resume_button.setVisible(resume > 0 and not played)
        if resume > 0 and not played:
            self.play_button.setText("▶  播放")
        else:
            self.play_button.setText("▶  播放")

        self.poster.set_item(item)
        self.poster.load_now()
        url = self.ctx.backdrop_url(item, 1600)
        if url:
            self.ctx.load_image(url, QSize(1600, 700), self._apply_backdrop)
        else:
            self._backdrop = None
            self.update()

    def update_sources(self, sources: List[dict]) -> None:
        previous_source = self.current_source_id()
        self._sources = sources or []
        self._populate_versions(previous_source)
        self._refresh_chips()

    def _populate_versions(self, preferred: str = "") -> None:
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for source in self._sources:
            self.version_combo.addItem(source_label(source), source.get("Id", ""))
        if preferred:
            index = self.version_combo.findData(preferred)
            if index >= 0:
                self.version_combo.setCurrentIndex(index)
        self.version_combo.blockSignals(False)
        self._update_version_icons()
        multiple = len(self._sources) > 1
        self.version_combo.setVisible(multiple)
        self.version_label.setVisible(multiple)

    def _update_version_icons(self) -> None:
        current = self.version_combo.currentIndex()
        for index in range(self.version_combo.count()):
            self.version_combo.setItemIcon(
                index,
                icon("check", 16, theme.ACCENT) if index == current else QIcon(),
            )

    def _on_version_changed(self, _index: int) -> None:
        self._update_version_icons()
        self._refresh_chips()
        self.version_changed.emit(self.current_source_id())

    def current_source(self) -> Optional[dict]:
        source_id = self.current_source_id()
        for source in self._sources:
            if source.get("Id") == source_id:
                return source
        return self._sources[0] if self._sources else None

    def current_source_id(self) -> str:
        if not self._sources:
            return ""
        data = self.version_combo.currentData()
        if data:
            return str(data)
        return str(self._sources[0].get("Id", ""))

    def _refresh_chips(self) -> None:
        while self.chips_layout.count() > 1:
            child = self.chips_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        chips: List[str] = []
        if self._item is not None:
            if self._item.get("OfficialRating"):
                chips.append(self._item["OfficialRating"])
            if self._item.get("CommunityRating"):
                chips.append(f"★ {self._item['CommunityRating']:.1f}")
        chips.extend(media_chips(self.current_source() or {}))
        if self._item is not None:
            chips.extend((self._item.get("Genres") or [])[:4])
        for text in chips:
            self.chips_layout.insertWidget(self.chips_layout.count() - 1, Chip(text))
        self.chips_widget.setVisible(bool(chips))

    def set_play_label(self, text: str) -> None:
        self.play_button.setText(text)

    def _resume(self) -> None:
        if self._item is None:
            return
        ticks = int((self._item.get("UserData") or {}).get("PlaybackPositionTicks") or 0)
        self.play_requested.emit(ticks)

    def _meta_text(self, item: dict) -> str:
        parts = []
        if item.get("ProductionYear"):
            parts.append(str(item["ProductionYear"]))
        kind = _kind_text(item)
        if kind:
            parts.append(kind)
        if item.get("RunTimeTicks"):
            parts.append(parse_runtime(item["RunTimeTicks"]))
        if item.get("PremiereDate"):
            parts.append(str(item["PremiereDate"])[:10])
        return "   ·   ".join(parts)

    def _apply_backdrop(self, pixmap: QPixmap) -> None:
        self._backdrop = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect())
        painter.fillRect(rect, QColor("#10141b"))
        if self._backdrop is not None and not self._backdrop.isNull():
            painter.drawPixmap(rect.toRect(), self._backdrop)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor("#1c2a3d"))
            gradient.setColorAt(1.0, QColor("#0f131a"))
            painter.fillRect(rect, gradient)

        vertical = QLinearGradient(rect.bottomLeft(), rect.topLeft())
        vertical.setColorAt(0.0, QColor(16, 20, 27, 255))
        vertical.setColorAt(0.30, QColor(16, 20, 27, 235))
        vertical.setColorAt(1.0, QColor(16, 20, 27, 60))
        painter.fillRect(rect, vertical)

        horizontal = QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0.0, QColor(14, 17, 22, 220))
        horizontal.setColorAt(0.65, QColor(14, 17, 22, 40))
        painter.fillRect(rect, horizontal)
        painter.end()


class DetailPage(QWidget):
    back_requested = Signal()
    play_requested = Signal(dict, object)
    open_item = Signal(dict)
    state_changed = Signal()

    def __init__(self, ctx: AppContext, item: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._summary = item
        self.item_id = str(item.get("Id", ""))
        self._item: Optional[dict] = None
        self._episodes: List[dict] = []
        self._seasons: List[dict] = []
        self._season_id = ""
        self._episode_page = 0
        self._page_size = 30
        self._pagers: List[dict] = []
        self._season_combo: Optional[QComboBox] = None
        self._episode_box: Optional[QVBoxLayout] = None
        self._build_ui()
        self._load()

    # ---- UI -------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll)

        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 48)
        self.body.setSpacing(28)
        self.scroll.setWidget(self.content)

        self.header = DetailHeader(self.ctx)
        self.header.back_requested.connect(self.back_requested)
        self.header.play_requested.connect(self._on_play_clicked)
        self.header.favorite_requested.connect(self._toggle_favorite)
        self.header.played_requested.connect(self._toggle_played)
        self.body.addWidget(self.header)

        self.body_container = QWidget()
        self.body_layout = QVBoxLayout(self.body_container)
        self.body_layout.setContentsMargins(36, 0, 36, 0)
        self.body_layout.setSpacing(26)
        self.body.addWidget(self.body_container)

        self.loading = QLabel("正在加载详情…")
        self.loading.setObjectName("muted")
        self.loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_layout.addWidget(self.loading)

        self.cast_section = QWidget()
        self.cast_layout = QVBoxLayout(self.cast_section)
        self.cast_layout.setContentsMargins(0, 0, 0, 0)
        self.cast_layout.setSpacing(12)
        self.cast_section.setVisible(False)
        self.body_layout.addWidget(self.cast_section)

        self.series_section = QWidget()
        series_layout = QVBoxLayout(self.series_section)
        series_layout.setContentsMargins(0, 0, 0, 0)
        series_layout.setSpacing(12)
        series_header = SectionHeader("剧集")
        series_layout.addWidget(series_header)
        self._season_combo = RoundedComboBox()
        self._season_combo.setMaximumWidth(240)
        self._season_combo.currentIndexChanged.connect(self._on_season_changed)
        series_layout.addWidget(self._season_combo)
        self._episode_box = QVBoxLayout()
        self._episode_box.setSpacing(8)

        # 分页控件：上下各放一组，长剧集（100+ 集）不必来回滚动
        self._pagers = []
        series_layout.addWidget(self._create_pager())
        series_layout.addLayout(self._episode_box)
        self._bottom_pager = self._create_pager()
        series_layout.addWidget(self._bottom_pager)
        self._series_header = series_header
        self.series_section.setVisible(False)
        self.body_layout.addWidget(self.series_section)

        self.episode_section = QWidget()
        episode_layout = QVBoxLayout(self.episode_section)
        episode_layout.setContentsMargins(0, 0, 0, 0)
        episode_layout.setSpacing(12)
        episode_layout.addWidget(SectionHeader("本集"))
        self._single_episode_box = QVBoxLayout()
        self._single_episode_box.setSpacing(8)
        episode_layout.addLayout(self._single_episode_box)
        self.episode_section.setVisible(False)
        self.body_layout.addWidget(self.episode_section)

        self.similar_row = PosterRow(self.ctx, "相似推荐", card_width=170)
        self.similar_row.activated.connect(self.open_item)
        self.similar_row.play_requested.connect(lambda item: self.play_requested.emit(item, 0))
        self.similar_row.setVisible(False)
        self.body_layout.addWidget(self.similar_row)

        self.children_row = PosterRow(self.ctx, "包含内容", card_width=170)
        self.children_row.activated.connect(self.open_item)
        self.children_row.play_requested.connect(lambda item: self.play_requested.emit(item, 0))
        self.children_row.setVisible(False)
        self.body_layout.addWidget(self.children_row)

    # ---- 数据 -----------------------------------------------------------
    def _load(self) -> None:
        run_async(
            self.ctx.client.get_item,
            self.item_id,
            on_done=self._on_item,
            on_error=self._on_error,
        )

    def _on_error(self, message: str) -> None:
        self.loading.setText(f"加载失败：{message}")

    def _on_item(self, item: dict) -> None:
        self._item = item
        self.loading.setVisible(False)
        self.header.set_item(item)

        if item.get("Type") == "Series":
            self.header.set_play_label("▶  播放")
            run_async(self.ctx.client.get_seasons, self.item_id, on_done=self._on_seasons, on_error=lambda _m: None)
        elif item.get("Type") == "BoxSet":
            run_async(
                self.ctx.client.get_items,
                parent_id=self.item_id,
                recursive=False,
                include_types="Movie,Series,Video,BoxSet",
                limit=40,
                sort_by="SortName",
                on_done=self._on_children,
                on_error=lambda _m: None,
            )
        elif item.get("Type") == "Episode":
            self.episode_section.setVisible(True)
            row = EpisodeRow(self.ctx, item)
            row.play_requested.connect(lambda ep: self.play_requested.emit(ep, 0))
            self._single_episode_box.addWidget(row)
        else:
            self._load_similar()

        sources = item.get("MediaSources") or []
        streams = (sources[0].get("MediaStreams") if sources else None) or []
        if item.get("Type") in ("Movie", "Episode", "Video") and not streams:
            # 详情接口不一定带 MediaStreams，用 PlaybackInfo 补齐分辨率/音轨信息
            run_async(
                self.ctx.client.playback_info,
                self.item_id,
                on_done=self._on_streams,
                on_error=lambda _m: None,
            )

        self._build_cast(item)

    def _on_streams(self, info: dict) -> None:
        sources = info.get("MediaSources") or []
        if not sources or self._item is None:
            return
        self._item["MediaSources"] = sources
        self.header.update_sources(sources)

    def media_source_id_for(self, item: dict) -> str:
        if str(item.get("Id", "")) != self.item_id:
            return ""
        return self.header.current_source_id()

    def _build_cast(self, item: dict) -> None:
        people = [p for p in (item.get("People") or []) if p.get("Id")][:16]
        if not people:
            return
        while self.cast_layout.count():
            child = self.cast_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.cast_layout.addWidget(SectionHeader("演职人员"))
        self.cast_layout.addWidget(PersonRow(self.ctx, people))
        self.cast_section.setVisible(True)

    def _on_seasons(self, seasons: List[dict]) -> None:
        self._seasons = seasons
        if not seasons:
            return
        self._season_combo.blockSignals(True)
        self._season_combo.clear()
        for season in seasons:
            name = season.get("Name") or f"第 {season.get('IndexNumber', '?')} 季"
            self._season_combo.addItem(name, season.get("Id", ""))
        self._season_combo.blockSignals(False)
        self.series_section.setVisible(True)
        self._season_id = seasons[0].get("Id", "")
        self._load_episodes(self._season_id)

    def _on_season_changed(self, _index: int) -> None:
        season_id = self._season_combo.currentData() or ""
        if season_id and season_id != self._season_id:
            self._season_id = season_id
            self._episode_page = 0
            self._load_episodes(season_id)

    def _load_episodes(self, season_id: str) -> None:
        run_async(
            self.ctx.client.get_episodes,
            self.item_id,
            season_id,
            on_done=self._on_episodes,
            on_error=lambda _m: None,
        )

    def _on_episodes(self, episodes: List[dict]) -> None:
        self._episodes = episodes
        if self._episode_box is None:
            return
        self._series_header.set_title(f"剧集 · 共 {len(episodes)} 集" if episodes else "剧集")
        if not episodes:
            clear_layout(self._episode_box)
            label = QLabel("该季暂无剧集")
            label.setObjectName("muted")
            self._episode_box.addWidget(label)
            for pager in self._pagers:
                pager["widget"].setVisible(False)
            return
        # 默认跳到第一个未看剧集所在页，方便继续追番
        self._episode_page = 0
        for index, episode in enumerate(episodes):
            if not (episode.get("UserData") or {}).get("Played"):
                self._episode_page = index // self._page_size
                break
        self._build_page_combo()
        self._render_episode_page()

    def _create_pager(self) -> QWidget:
        pager = QWidget()
        layout = QHBoxLayout(pager)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        info = QLabel("")
        info.setObjectName("muted")
        info.setStyleSheet("font-size: 12px;")
        layout.addWidget(info)
        layout.addStretch(1)
        prev_button = make_button("上一页", "chip")
        prev_button.clicked.connect(lambda: self._go_page(self._episode_page - 1))
        layout.addWidget(prev_button)
        combo = QComboBox()
        combo.setMinimumWidth(120)
        combo.currentIndexChanged.connect(self._on_page_changed)
        layout.addWidget(combo)
        next_button = make_button("下一页", "chip")
        next_button.clicked.connect(lambda: self._go_page(self._episode_page + 1))
        layout.addWidget(next_button)
        pager.setVisible(False)
        self._pagers.append(
            {"widget": pager, "info": info, "prev": prev_button, "combo": combo, "next": next_button}
        )
        return pager

    def _page_count(self) -> int:
        return max(1, math.ceil(len(self._episodes) / self._page_size))

    def _build_page_combo(self) -> None:
        pages = self._page_count()
        for pager in self._pagers:
            combo = pager["combo"]
            combo.blockSignals(True)
            combo.clear()
            for index in range(pages):
                combo.addItem(f"第 {index + 1} / {pages} 页", index)
            combo.blockSignals(False)

    def _render_episode_page(self) -> None:
        if self._episode_box is None:
            return
        clear_layout(self._episode_box)
        pages = self._page_count()
        self._episode_page = max(0, min(self._episode_page, pages - 1))
        start = self._episode_page * self._page_size
        for episode in self._episodes[start:start + self._page_size]:
            row = EpisodeRow(self.ctx, episode)
            row.play_requested.connect(lambda ep: self.play_requested.emit(ep, 0))
            self._episode_box.addWidget(row)

        total = len(self._episodes)
        for pager in self._pagers:
            pager["info"].setText(f"共 {total} 集 · 每页 {self._page_size} 集")
            pager["prev"].setEnabled(self._episode_page > 0)
            pager["next"].setEnabled(self._episode_page < pages - 1)
            pager["combo"].blockSignals(True)
            pager["combo"].setCurrentIndex(self._episode_page)
            pager["combo"].blockSignals(False)
            pager["widget"].setVisible(total > self._page_size)

    def _go_page(self, page: int) -> None:
        if not self._episodes:
            return
        pages = self._page_count()
        page = max(0, min(page, pages - 1))
        if page == self._episode_page:
            return
        self._episode_page = page
        self._render_episode_page()
        QTimer.singleShot(
            0, lambda: self.scroll.ensureWidgetVisible(self.series_section, 0, 24)
        )

    def _on_page_changed(self, _index: int) -> None:
        combo = self.sender()
        if combo is None:
            return
        page = combo.currentData()
        if page is not None:
            self._go_page(int(page))

    def _on_children(self, data: dict) -> None:
        items = data.get("Items", [])
        if items:
            self.children_row.set_items(items)
            self.children_row.setVisible(True)

    def _load_similar(self) -> None:
        run_async(
            self.ctx.client.get_similar,
            self.item_id,
            12,
            on_done=self._on_similar,
            on_error=lambda _m: None,
        )

    def _on_similar(self, items: List[dict]) -> None:
        if items:
            self.similar_row.set_items(items)
            self.similar_row.setVisible(True)

    # ---- 操作 -----------------------------------------------------------
    def _on_play_clicked(self, _start: int) -> None:
        item = self._item or self._summary
        if item.get("Type") == "Series":
            episode = self._first_episode()
            if episode is not None:
                self.play_requested.emit(episode, 0)
            return
        start = int(_start or 0)
        if start <= 0:
            start = int(
                (self._summary.get("UserData") or {}).get("PlaybackPositionTicks") or 0
            )
        if item.get("Id") != self._summary.get("Id"):
            start = 0
        self.play_requested.emit(item, start)

    def _first_episode(self) -> Optional[dict]:
        for episode in self._episodes:
            if not (episode.get("UserData") or {}).get("Played"):
                return episode
        return self._episodes[0] if self._episodes else None

    def episode_playlist(self, item: dict) -> tuple:
        """返回 (当前季剧集列表, item 的下标)，用于连播。"""
        item_id = item.get("Id")
        for index, episode in enumerate(self._episodes):
            if episode.get("Id") == item_id:
                return list(self._episodes), index
        return [], -1

    def refresh(self) -> None:
        self._load()
        if self._seasons:
            self._load_episodes(self._season_id)

    def _toggle_favorite(self) -> None:
        item = self._item or self._summary
        current = bool((item.get("UserData") or {}).get("IsFavorite"))
        target = not current

        def done(_result=None) -> None:
            item.setdefault("UserData", {})["IsFavorite"] = target
            self.header.set_item(item)
            self.state_changed.emit()

        run_async(self.ctx.client.set_favorite, item["Id"], target, on_done=done)

    def _toggle_played(self) -> None:
        item = self._item or self._summary
        current = bool((item.get("UserData") or {}).get("Played"))
        target = not current

        def done(_result=None) -> None:
            user_data = item.setdefault("UserData", {})
            user_data["Played"] = target
            if target:
                user_data["PlaybackPositionTicks"] = 0
            self.header.set_item(item)
            self.state_changed.emit()

        run_async(self.ctx.client.set_played, item["Id"], target, on_done=done)
