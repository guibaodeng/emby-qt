"""播放器窗口：libVLC 视频表面 + 悬浮控制栏 + 进度上报。"""

from __future__ import annotations

import os
import sys
import time
from typing import List, Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPalette, QPen, QPixmap, QRegion, QShortcut
from PySide6.QtGui import QGuiApplication, QImage, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import CLIENT_NAME
from ..api import TICKS
from ..async_task import run_async
from ..context import AppContext
from ..logging_setup import get_logger
from ..player import VLC_AVAILABLE, PlaybackReporter, VlcEngine, ms_to_ticks, vlc_error
from ..mpv_player import MPV_AVAILABLE, MpvEngine, MpvVideoSurface, mpv_error
from . import theme
from .branding import app_icon
from .frameless import create_resize_handles, position_resize_handles
from .icons import icon
from .titlebar import TitleBar
from .widgets import make_button


def _target_video_size(source: dict) -> tuple:
    """按视频宽高比计算 vmem 渲染尺寸（宽度固定 1600）。"""
    width = height = 0
    for stream in source.get("MediaStreams") or []:
        if stream.get("Type") == "Video" and stream.get("Width") and stream.get("Height"):
            width = int(stream["Width"])
            height = int(stream["Height"])
            break
    if width <= 0 or height <= 0:
        return 1600, 900
    target_width = 1600
    target_height = max(2, round(target_width * height / width))
    return target_width, target_height - target_height % 2


def _fmt(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def select_player_backend() -> str:
    """选择播放内核：mpv（默认）或 vlc。"""
    pref = os.environ.get("EMBYQT_PLAYER", "mpv").strip().lower()
    if pref not in ("mpv", "vlc"):
        pref = "mpv"
    if pref == "mpv" and MPV_AVAILABLE:
        return "mpv"
    if VLC_AVAILABLE:
        return "vlc"
    if MPV_AVAILABLE:
        return "mpv"
    return ""


def native_video_platform() -> bool:
    """能否让 libVLC 直接嵌入原生窗口。

    macOS 统一走 vmem：NSView 子窗口不易参与 Qt 圆角裁剪，vmem 更稳定。
    """
    if sys.platform == "darwin":
        return False
    if not sys.platform.startswith("linux"):
        return True
    return QGuiApplication.platformName() in ("xcb", "x11")


class VideoSurface(QWidget):
    clicked = Signal(float)
    double_clicked = Signal()
    mouse_moved = Signal()

    def __init__(self, parent: Optional[QWidget] = None, native: bool = False) -> None:
        super().__init__(parent)
        self._native = native
        self._corner_radius = 16
        self._frame: Optional[QImage] = None
        self._frame_bytes: Optional[bytes] = None
        if native:
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        else:
            # vmem 模式自己画黑底，禁用自动填充，避免底部圆角外露出黑边
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        if native:
            self.setAutoFillBackground(True)
            palette = self.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#000000"))
            self.setPalette(palette)
        else:
            self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pending_click_ratio = 0.0
        self._suppress_next_click = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        # 等系统双击间隔结束再判定单击，避免双击全屏时先触发一次 seek
        self._click_timer.setInterval(
            max(220, QApplication.doubleClickInterval() + 20)
        )
        self._click_timer.timeout.connect(self._emit_click)

    def set_frame(self, data: bytes, width: int, height: int, pitch: int) -> None:
        """接收 VLC vmem 渲染出的一帧（RV32）。"""
        self._frame_bytes = data
        self._frame = QImage(data, width, height, pitch, QImage.Format.Format_RGB32)
        self.update()

    def clear_frame(self) -> None:
        self._frame = None
        self._frame_bytes = None
        self.update()

    def has_frame(self) -> bool:
        return self._frame is not None

    def set_corner_radius(self, radius: int) -> None:
        self._corner_radius = int(radius)
        self._apply_mask()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_mask()

    def _apply_mask(self) -> None:
        # 原生视频窗口不参与 Qt mask（X11 上可能触发窗口系统错误）；
        # 底部 20px 由 _layout_media 让出，交给控制栏覆盖。
        if self._native or self.width() <= 0 or self.height() <= 0:
            return
        # 比控制栏的 16px 圆角再大一点，避免半透明控制栏圆角外露出视频黑边
        radius = float(self._corner_radius + 4)
        if radius <= 4:
            self.clearMask()
            return
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.moveTo(rect.topLeft())
        path.lineTo(rect.topRight())
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
        path.lineTo(rect.left() + radius, rect.bottom())
        path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
        path.closeSubpath()
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._native:
            return  # 画面由 libVLC 直接绘制
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._corner_radius > 0:
            # 只圆底部两个角：顶部与标题栏齐平
            radius = float(self._corner_radius)
            rect = QRectF(self.rect())
            path = QPainterPath()
            path.moveTo(rect.topLeft())
            path.lineTo(rect.topRight())
            path.lineTo(rect.right(), rect.bottom() - radius)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
            path.lineTo(rect.left() + radius, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
            path.closeSubpath()
            painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self._frame is not None and not self._frame.isNull():
            target = self.rect()
            scaled = self._frame.size().scaled(
                target.size(), Qt.AspectRatioMode.KeepAspectRatio
            )
            x = (target.width() - scaled.width()) // 2
            y = (target.height() - scaled.height()) // 2
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(QRect(x, y, scaled.width(), scaled.height()), self._frame)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.mouse_moved.emit()
        super().mouseMoveEvent(event)

    def _emit_click(self) -> None:
        self.clicked.emit(self._pending_click_ratio)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._suppress_next_click:
                self._suppress_next_click = False
                self._click_timer.stop()
            else:
                self._pending_click_ratio = max(
                    0.0, min(1.0, event.position().x() / max(1, self.width()))
                )
                self._click_timer.start()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._suppress_next_click = True
            self._click_timer.stop()
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


log = get_logger("player")


class ProgressSlider(QSlider):
    """播放进度条：点击/拖动定位。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, 1000)
        self.setMinimumHeight(20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pressed = False
        self._buffered_ranges = []

    def set_buffered_ranges(self, ranges) -> None:
        cleaned = []
        for start, end in ranges or []:
            start = max(0.0, min(100.0, float(start)))
            end = max(0.0, min(100.0, float(end)))
            if end > start:
                cleaned.append((start, end))
        if cleaned != self._buffered_ranges:
            self._buffered_ranges = cleaned
            self.update()

    def clear_buffered(self) -> None:
        if self._buffered_ranges:
            self._buffered_ranges = []
            self.update()

    def _value_at(self, x: float) -> int:
        left, right = 7.0, self.width() - 7.0
        if right <= left:
            return self.minimum()
        ratio = (x - left) / (right - left)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.sliderPressed.emit()
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pressed:
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event.position().x()))
            self._pressed = False
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = self.width(), self.height()
        bar_height = 4.0
        left, right = 7.0, width - 7.0
        if right <= left:
            return
        top = (height - bar_height) / 2
        radius = bar_height / 2
        painter.setPen(Qt.PenStyle.NoPen)

        light = theme.SCHEME == "light"
        track_color = QColor(0, 0, 0, 40) if light else QColor(255, 255, 255, 38)
        painter.setBrush(track_color)
        painter.drawRoundedRect(QRectF(left, top, right - left, bar_height), radius, radius)

        span = self.maximum() - self.minimum()
        ratio = (self.value() - self.minimum()) / span if span > 0 else 0.0
        played_width = (right - left) * max(0.0, min(1.0, ratio))
        played_x = left + played_width
        played_pct = ratio * 100.0

        if self._buffered_ranges:
            buffer_color = (
                QColor(126, 138, 158, 145) if light else QColor(205, 214, 228, 85)
            )
            painter.setBrush(buffer_color)
            for start_pct, end_pct in self._buffered_ranges:
                start_x = left + (right - left) * start_pct / 100.0
                end_x = left + (right - left) * end_pct / 100.0
                if end_x - start_x > 0.5:
                    painter.drawRoundedRect(
                        QRectF(start_x, top, end_x - start_x, bar_height),
                        radius,
                        radius,
                    )

        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(QRectF(left, top, played_width, bar_height), radius, radius)

        painter.setBrush(QColor(theme.TEXT))
        painter.drawEllipse(QPointF(left + played_width, height / 2.0), 6, 6)


class PauseOverlay(QWidget):
    """暂停时显示在画面正中的半透明暂停图标。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawEllipse(self.rect())
        painter.setBrush(QColor(255, 255, 255, 235))
        bar_width, bar_height, gap = 16.0, 54.0, 16.0
        cx, cy = self.width() / 2.0, self.height() / 2.0
        painter.drawRoundedRect(
            QRectF(cx - gap / 2 - bar_width, cy - bar_height / 2, bar_width, bar_height), 4, 4
        )
        painter.drawRoundedRect(
            QRectF(cx + gap / 2, cy - bar_height / 2, bar_width, bar_height), 4, 4
        )


class LoadingOverlay(QWidget):
    """加载中：与暂停遮罩同尺寸的转圈 + 下方网速。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(160, 200)
        self._angle = 0
        self._speed: Optional[float] = None
        self._direct = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)

    def _advance(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def set_speed(self, bytes_per_second: Optional[float], direct: bool = False) -> None:
        self._speed = bytes_per_second
        self._direct = direct
        self.update()

    @staticmethod
    def _format_speed(value: float) -> str:
        value = max(0.0, float(value))
        if value < 1024:
            return f"{value:.0f} B/s"
        if value < 1024 ** 2:
            return f"{value / 1024:.1f} KB/s"
        if value < 1024 ** 3:
            return f"{value / (1024 ** 2):.1f} MB/s"
        return f"{value / (1024 ** 3):.2f} GB/s"

    def _value_at(self, x: float) -> int:
        left, right = 7.0, self.width() - 7.0
        if right <= left:
            return self.minimum()
        ratio = (x - left) / (right - left)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.sliderPressed.emit()
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pressed:
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event.position().x()))
            self._pressed = False
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        circle = QRectF(0, 0, 160, 160)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawEllipse(circle)

        ring = QRectF(20, 20, 120, 120)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 45), 4))
        painter.drawEllipse(ring)
        pen = QPen(QColor(255, 255, 255, 235), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(ring, self._angle * 16, 270 * 16)

        painter.setPen(QColor(214, 222, 236))
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, 163, 160, 16),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "加载中…",
        )
        if self._direct:
            text = "直连"
        elif self._speed is None:
            text = "测速中…"
        else:
            text = self._format_speed(self._speed)
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            QRectF(0, 178, 160, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )


class VolumePopup(QFrame):
    """悬停音量图标时浮出的音量滑条。"""

    def __init__(self, player: "PlayerWindow") -> None:
        super().__init__(player)
        self.player = player
        self.setObjectName("volumePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(58, 178)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(4)
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setFixedHeight(122)
        self.slider.setFixedWidth(30)
        self.slider.valueChanged.connect(self.player.set_volume)
        layout.addWidget(self.slider, 0, Qt.AlignmentFlag.AlignHCenter)
        self.value_label = QLabel("")
        self.value_label.setObjectName("volumeValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)
        self._apply_style()
        theme.signals.changed.connect(self._apply_style)
        self.set_value(player.volume)

    def set_value(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.value_label.setText(f"{value}%")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#volumePopup {{
                background: {theme.SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
            }}
            QLabel#volumeValue {{
                color: {theme.TEXT_MUTED};
                font-size: 10px;
            }}
            """
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        self.player._cancel_hide_volume_popup()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.player._schedule_hide_volume_popup()
        super().leaveEvent(event)


class ControlBar(QFrame):
    def __init__(self, player: "PlayerWindow", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.player = player
        self.setObjectName("controlBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._rounded = True
        self._playing = False
        self._muted = False
        self._fullscreen = False
        self._apply_style()
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 12)
        layout.setSpacing(4)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.current_time = QLabel("0:00")
        self.current_time.setObjectName("controlTime")
        self.current_time.setFixedWidth(60)
        self.current_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seek_row.addWidget(self.current_time)
        self.seek = ProgressSlider()
        self.seek.sliderPressed.connect(self.player.on_seek_started)
        self.seek.sliderReleased.connect(self.player.on_seek_finished)
        self.seek.valueChanged.connect(self.player.on_seek_value)
        seek_row.addWidget(self.seek, 1)
        self.total_time = QLabel("0:00")
        self.total_time.setObjectName("controlTime")
        self.total_time.setFixedWidth(60)
        self.total_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seek_row.addWidget(self.total_time)
        layout.addLayout(seek_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.play_button = self._icon_button("play", "播放 / 暂停（空格）", 40)
        self.play_button.clicked.connect(self.player.toggle_pause)
        buttons.addWidget(self.play_button)

        self.back_button = self._icon_button("back10", "后退 10 秒（←）")
        self.back_button.clicked.connect(lambda: self.player.seek_relative(-10_000))
        buttons.addWidget(self.back_button)

        self.forward_button = self._icon_button("forward10", "前进 10 秒（→）")
        self.forward_button.clicked.connect(lambda: self.player.seek_relative(10_000))
        buttons.addWidget(self.forward_button)

        self.volume_button = self._icon_button("volume", "静音（M）· 悬停调节音量")
        self.volume_button.clicked.connect(self.player.toggle_mute)
        self.volume_button.installEventFilter(self)
        buttons.addWidget(self.volume_button)

        self.speed_icon = QLabel()
        self.speed_icon.setPixmap(icon("speed", 24, theme.TEXT).pixmap(24, 24))
        self.speed_icon.hide()
        buttons.addWidget(self.speed_icon)
        self.speed_label = QLabel("")
        self.speed_label.setObjectName("controlSpeed")
        self.speed_label.hide()
        buttons.addWidget(self.speed_label)

        self.buffer_label = QLabel("")
        self.buffer_label.setObjectName("controlBuffer")
        self.buffer_label.hide()
        buttons.addWidget(self.buffer_label)

        buttons.addStretch(1)

        self.audio_button = self._icon_button("audio", "选择音轨")
        self.subtitle_button = self._icon_button("subtitle", "选择字幕")
        self.subtitle_button.clicked.connect(self.player.show_subtitle_menu)
        self.audio_button.clicked.connect(self.player.show_audio_menu)
        buttons.addWidget(self.audio_button)
        buttons.addWidget(self.subtitle_button)

        self.fullscreen_button = self._icon_button("fullscreen", "全屏（F）")
        self.fullscreen_button.clicked.connect(self.player.toggle_fullscreen)
        buttons.addWidget(self.fullscreen_button)

        layout.addLayout(buttons)
        theme.signals.changed.connect(self.refresh_theme)

    def _icon_button(self, name: str, tooltip: str, width: int = 36) -> QPushButton:
        button = make_button("", "iconButton")
        button.setIcon(icon(name, 24, theme.TEXT))
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(width, 36)
        return button

    def update_play_icon(self, playing: bool) -> None:
        self._playing = bool(playing)
        self.play_button.setIcon(
            icon("pause" if self._playing else "play", 24, theme.TEXT)
        )

    def update_volume_icon(self, muted: bool) -> None:
        self._muted = bool(muted)
        self.volume_button.setIcon(
            icon("muted" if self._muted else "volume", 24, theme.TEXT)
        )

    def update_fullscreen_icon(self, fullscreen: bool) -> None:
        self._fullscreen = bool(fullscreen)
        self.fullscreen_button.setIcon(
            icon("restore" if self._fullscreen else "fullscreen", 24, theme.TEXT)
        )

    def refresh_theme(self) -> None:
        self._apply_style()
        color = theme.TEXT
        self.play_button.setIcon(icon("pause" if self._playing else "play", 24, color))
        self.back_button.setIcon(icon("back10", 24, color))
        self.forward_button.setIcon(icon("forward10", 24, color))
        self.volume_button.setIcon(icon("muted" if self._muted else "volume", 24, color))
        self.audio_button.setIcon(icon("audio", 24, color))
        self.subtitle_button.setIcon(icon("subtitle", 24, color))
        self.fullscreen_button.setIcon(
            icon("restore" if self._fullscreen else "fullscreen", 24, color)
        )
        self.speed_icon.setPixmap(
            icon("speed", 24, theme.TEXT).pixmap(24, 24)
        )
        self.seek.update()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.volume_button:
            if event.type() == QEvent.Type.Enter:
                self.player.show_volume_popup()
            elif event.type() == QEvent.Type.Leave:
                self.player._schedule_hide_volume_popup()
        return super().eventFilter(obj, event)

    def set_speed(self, text: str) -> None:
        visible = bool(text)
        self.speed_label.setText(text)
        self.speed_label.setVisible(visible)
        self.speed_icon.setVisible(visible)

    def set_buffer(self, text: str) -> None:
        self.buffer_label.setText(text)
        self.buffer_label.setVisible(bool(text))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.player._show_controls()
        super().mouseMoveEvent(event)

    def _apply_style(self) -> None:
        radius = 16 if self._rounded else 0
        if theme.SCHEME == "light":
            # 透明度提高 10%（0.94 -> 0.84）
            background = "rgba(242, 245, 250, 0.84)"
            border = "rgba(0, 0, 0, 0.08)"
            hover = "rgba(0, 0, 0, 0.08)"
        else:
            # 透明度提高 10%（0.88 -> 0.78）
            background = "rgba(12, 15, 21, 0.78)"
            border = "rgba(255, 255, 255, 0.07)"
            hover = "rgba(255, 255, 255, 0.10)"
        self.setStyleSheet(
            f"""
            QFrame#controlBar {{
                background: {background};
                border-top: 1px solid {border};
                border-bottom-left-radius: {radius}px;
                border-bottom-right-radius: {radius}px;
            }}
            QPushButton#iconButton {{
                background: transparent;
                border: none;
            }}
            QPushButton#iconButton:hover {{
                background: {hover};
            }}
            QLabel#controlTime {{ color: {theme.TEXT}; font-size: 12px; }}
            QLabel#controlSpeed {{ color: {theme.TEXT_MUTED}; font-size: 11px; }}
            QLabel#controlBuffer {{ color: {theme.TEXT_MUTED}; font-size: 11px; }}
            """
        )

    def set_rounded(self, rounded: bool) -> None:
        self._rounded = bool(rounded)
        self._apply_style()


class PlayerWindow(QWidget):
    closed = Signal()

    def __init__(
        self,
        ctx: AppContext,
        item: dict,
        start_ticks: int = 0,
        playlist: Optional[List[dict]] = None,
        index: int = -1,
        media_source_id: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.media_source_id = media_source_id or ""
        self._has_system_proxy = False
        self._backend = select_player_backend()
        self._native_video = (
            self._backend == "vlc" and native_video_platform()
        )
        self._vmem_connected = False
        self.item = item
        self.start_ticks = int(start_ticks or 0)
        self.playlist = playlist or []
        self.index = index
        self.volume = ctx.config.volume

        self.setWindowTitle(f"播放 · {item.get('Name', '')}")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(900, 560)
        self.resize(1280, 760)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._media_source: Optional[dict] = None
        self._play_session_id = ""
        self._reporter: Optional[PlaybackReporter] = None
        self._engine = None
        self._duration_ms = 0
        self._seeking = False
        self._muted = False
        self._closing = False
        self._loading = False
        self._load_seq = 0
        self._last_report_ms = 0
        self._last_position_ms = 0
        self._error_shown = False
        self._playback_started = False
        self._has_video = True
        self._loading_since = time.monotonic()
        self._speed_last_time: Optional[float] = None
        self._speed_last_bytes = 0
        self._speed_value = 0.0
        self._start_position_ms = int(start_ticks // 10_000)
        self._using_proxy = self._has_system_proxy
        self._retried_stream = False
        self._controls_visible = True

        self._build_ui()
        self._install_shortcuts()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(500)
        self._ui_timer.timeout.connect(self._tick)
        self._ui_timer.start()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(10_000)
        self._hide_timer.timeout.connect(self._maybe_hide_controls)

        self._apply_window_state()
        self._load(item, self.start_ticks)

    # ---- UI -------------------------------------------------------------
    def _build_ui(self) -> None:
        self.container = QWidget(self)
        self.container.setStyleSheet("background: transparent;")

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self.player_frame = QFrame()
        self.player_frame.setObjectName("playerFrame")
        self.player_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._outer.addWidget(self.player_frame)

        root = QVBoxLayout(self.player_frame)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.title_bar = TitleBar(
            self._title_text(), app_icon(), show_tooltips=False, parent=self.player_frame
        )
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.close_requested.connect(self.close)
        self.title_bar.maximize_requested.connect(self._toggle_maximized)
        root.addWidget(self.title_bar)
        root.addWidget(self.container, 1)
        self._handles = create_resize_handles(self)

        if self._backend == "mpv":
            self.video = MpvVideoSurface(self.container)
        else:
            self.video = VideoSurface(self.container, native=self._native_video)
        self.pause_overlay = PauseOverlay(self.container)
        self.pause_overlay.hide()
        self.loading_overlay = LoadingOverlay(self.container)
        self.loading_overlay.hide()
        self.video.clicked.connect(lambda _ratio: self.toggle_pause())
        self.video.double_clicked.connect(self.toggle_fullscreen)
        self.video.mouse_moved.connect(self._on_mouse_moved)

        self.controls = ControlBar(self, self.container)
        if self._native_video:
            # 原生视频窗口会盖住普通子控件，控制栏也必须原生
            self.controls.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)

        self.volume_popup = VolumePopup(self)
        self.volume_popup.hide()
        self._volume_hide_timer = QTimer(self)
        self._volume_hide_timer.setSingleShot(True)
        self._volume_hide_timer.setInterval(260)
        self._volume_hide_timer.timeout.connect(self._hide_volume_popup)

        self.status_label = QLabel("正在准备播放…", self.container)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(
            "color: #aeb7c8; font-size: 14px; background: transparent;"
        )
        if self._native_video:
            self.status_label.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._update_title()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_outer"):
            self._outer.activate()
        self._layout_media()
        # 布局激活后容器尺寸才最终确定，再补一次
        QTimer.singleShot(0, self._layout_media)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._layout_media)

    def _layout_media(self) -> None:
        if not hasattr(self, "controls"):
            return
        if hasattr(self, "_handles"):
            position_resize_handles(self, self._handles)
        rect = self.container.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        video_rect = QRect(rect)
        if self._native_video and not (self.isFullScreen() or self.isMaximized()):
            # 原生视频窗口不参与 Qt 圆角裁剪：底部让出 20px，由控制栏覆盖
            video_rect.setHeight(max(1, video_rect.height() - 20))
        self.video.setGeometry(video_rect)
        overlay_size = 160
        self.pause_overlay.setGeometry(
            (rect.width() - overlay_size) // 2,
            (rect.height() - overlay_size) // 2,
            overlay_size,
            overlay_size,
        )
        self.pause_overlay.raise_()
        loading_width, loading_height = 160, 200
        self.loading_overlay.setGeometry(
            (rect.width() - loading_width) // 2,
            (rect.height() - loading_height) // 2,
            loading_width,
            loading_height,
        )
        self.loading_overlay.raise_()
        height = 96
        self.controls.setGeometry(0, rect.height() - height, rect.width(), height)
        self.status_label.setGeometry(rect)
        if not self.controls.isVisible():
            self.controls.show()
        self.controls.raise_()
        self.status_label.raise_()
        if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
            self._position_volume_popup()
        if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
            self.volume_popup.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.controls.raise_()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._on_mouse_moved()
        super().mouseMoveEvent(event)

    # ---- 快捷键 ---------------------------------------------------------
    def _install_shortcuts(self) -> None:
        def shortcut(key: str, handler) -> None:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(handler)

        shortcut("Space", self.toggle_pause)
        shortcut("Left", lambda: self.seek_relative(-10_000))
        shortcut("Right", lambda: self.seek_relative(10_000))
        shortcut("Up", lambda: self.change_volume(5))
        shortcut("Down", lambda: self.change_volume(-5))
        shortcut("M", self.toggle_mute)
        shortcut("F", self.toggle_fullscreen)
        shortcut("Escape", self._on_escape)

    def _on_escape(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()
        else:
            self.close()

    # ---- 播放流程 -------------------------------------------------------
    def play_item(
        self,
        item: dict,
        start_ticks: int = 0,
        playlist: Optional[List[dict]] = None,
        index: int = -1,
        media_source_id: str = "",
    ) -> None:
        """在同一个播放器窗口里切换视频（重复点播不会开新窗口）。"""
        if not item:
            return
        same_media = (
            self._engine is not None
            and not self._closing
            and not self._error_shown
            and str(self.item.get("Id", "")) == str(item.get("Id", ""))
            and (media_source_id or "") == (self.media_source_id or "")
        )
        if same_media:
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
            return

        self._loading = True
        if hasattr(self, "pause_overlay"):
            self.pause_overlay.hide()
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.hide()
        self.media_source_id = media_source_id or ""
        if playlist is not None:
            self.playlist = list(playlist)
        self.index = index
        self._start_position_ms = int(start_ticks or 0) // 10_000
        self._last_position_ms = 0
        self._last_report_ms = 0
        self._duration_ms = 0
        self.controls.seek.setValue(0)
        self.controls.current_time.setText("0:00")
        self.controls.total_time.setText("0:00")
        self.video.clear_frame()
        if self._engine is not None:
            self._engine.stop()
        self._load(item, start_ticks)
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _load(self, item: dict, start_ticks: int) -> None:
        self.item = item
        self.start_ticks = start_ticks
        self._error_shown = False
        self._loading = True
        self._load_seq += 1
        self.controls.seek.setValue(0)
        if hasattr(self, "video"):
            self.video.clear_frame()
        seq = self._load_seq
        self.status_label.hide()
        self._playback_started = False
        self._loading_since = time.monotonic()
        self._speed_last_time = None
        self._speed_last_bytes = 0
        self._speed_value = 0.0
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.set_speed(None)
            self.loading_overlay.show()
            self.loading_overlay.raise_()
        self.controls.set_speed("测速中…")
        self._update_title()
        if self._reporter is not None:
            self._reporter.shutdown()
            self._reporter = None
        run_async(
            self.ctx.client.playback_info,
            item.get("Id", ""),
            self.media_source_id,
            on_done=lambda info: self._on_playback_info(info, start_ticks, seq),
            on_error=lambda message: self._on_error(message, seq),
        )

    def _on_error(self, message: str, seq: Optional[int] = None) -> None:
        if seq is not None and seq != self._load_seq:
            return
        self._loading = False
        self._error_shown = True
        if hasattr(self, "pause_overlay"):
            self.pause_overlay.hide()
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.hide()
        self.controls.set_speed("")
        self.status_label.setText(f"无法播放：{message}")
        log.error("播放失败：%s", message)
        self.status_label.show()
        self.status_label.raise_()

    def _on_media_failed(self, message: str) -> None:
        if self._retry_with_proxy():
            return
        self._on_error(message)

    def _on_playback_info(self, info: dict, start_ticks: int, seq: Optional[int] = None) -> None:
        if seq is not None and seq != self._load_seq:
            return
        sources = info.get("MediaSources") or []
        if not sources:
            self._on_error("服务器没有返回可用的媒体源", seq)
            return
        source = sources[0]
        if self.media_source_id:
            for candidate in sources:
                if candidate.get("Id") == self.media_source_id:
                    source = candidate
                    break
        self._media_source = source
        streams = source.get("MediaStreams") or []
        self._has_video = not streams or any(
            stream.get("Type") == "Video" for stream in streams
        )
        self._play_session_id = info.get("PlaySessionId") or ""
        media_source_id = source.get("Id") or ""

        if self._backend == "mpv":
            if not MPV_AVAILABLE:
                self._on_error(f"缺少 libmpv：{mpv_error()}")
                return
            if self._engine is None:
                try:
                    self._engine = MpvEngine(
                        self,
                        cache_bytes=self.ctx.config.mpv_cache_bytes,
                        cache_secs=self._mpv_cache_seconds(source),
                    )
                except Exception as exc:  # noqa: BLE001
                    self._on_error(str(exc))
                    return
                self._engine.ended.connect(
                    self._on_ended, Qt.ConnectionType.QueuedConnection
                )
                self._engine.failed.connect(
                    self._on_media_failed, Qt.ConnectionType.QueuedConnection
                )
                self._engine.set_volume(self.volume)
                self._engine.set_mute(self._muted)
            self.video.bind_engine(self._engine)
        elif self._backend == "vlc":
            if not VLC_AVAILABLE:
                self._on_error(f"缺少 libVLC：{vlc_error()}")
                return
            if self._engine is None:
                try:
                    self._engine = VlcEngine(self)
                except Exception as exc:  # noqa: BLE001
                    self._on_error(str(exc))
                    return
                self._engine.ended.connect(self._on_ended, Qt.ConnectionType.QueuedConnection)
                self._engine.failed.connect(self._on_media_failed, Qt.ConnectionType.QueuedConnection)
                self._engine.set_volume(self.volume)
                self._engine.set_mute(self._muted)
            if self._native_video:
                self._engine.attach(int(self.video.winId()))
            else:
                width, height = _target_video_size(source)
                self._engine.attach_vmem(width, height)
                if not self._vmem_connected:
                    self._engine.frame_ready.connect(
                        self.video.set_frame, Qt.ConnectionType.QueuedConnection
                    )
                    self._engine.frame_ready.connect(
                        self._on_frame_ready, Qt.ConnectionType.QueuedConnection
                    )
                    self._vmem_connected = True
        else:
            self._on_error("没有可用的播放内核（libmpv / libVLC 均不可用）")
            return

        self._reporter = PlaybackReporter(
            self.ctx.client,
            self.item["Id"],
            media_source_id,
            self._play_session_id,
        )
        self._reporter.start(start_ticks)

        self._start_position_ms = start_ticks // 10_000
        # 每次开始播放都强制复查系统代理（用户可能刚开启/关闭）
        self.ctx.proxy_manager.force_refresh()
        self._has_system_proxy = bool(self.ctx.proxy_manager.current())
        self._using_proxy = self._has_system_proxy
        self._retried_stream = False
        self._start_stream(media_source_id, self._play_session_id, self._start_position_ms)
        self._loading = False
        self.status_label.hide()
        self._update_pause_overlay()
        self._hide_timer.start()
        log.info(
            "开始播放：%s（源 %s，%s，起始 %.1fs）",
            self._title_text(), media_source_id or "-",
            "代理" if self._using_proxy else "直连", self._start_position_ms / 1000.0,
        )
        self.raise_()
        self.activateWindow()

    def _start_stream(self, media_source_id: str, play_session_id: str, start_ms: int) -> None:
        """默认直连（支持 Range 拖拽）；失败时再退回本机代理。"""
        if self._engine is None:
            return
        if self._using_proxy:
            url = self.ctx.proxy.media_url(self.item["Id"], media_source_id, play_session_id)
        else:
            url = (
                self.ctx.client.server
                + self.ctx.client.stream_path(self.item["Id"], media_source_id, play_session_id)
                + "&api_key="
                + self.ctx.client.token
            )
        expected_size = int((self._media_source or {}).get("Size") or 0)
        self.ctx.proxy.begin_playback(self.item.get("Id", ""), expected_size)
        self.controls.seek.clear_buffered()
        if self._backend == "mpv" and self._engine is not None:
            self._engine.update_cache(
                self.ctx.config.mpv_cache_bytes,
                self._mpv_cache_seconds(self._media_source),
            )
        self._speed_last_time = None
        self._speed_last_bytes = 0
        self._speed_value = 0.0
        self.controls.set_speed("测速中…")
        log.info(
            "打开媒体流：%s（%s，源 %s）",
            self._title_text(), "本机代理" if self._using_proxy else "直连",
            media_source_id or "-",
        )
        self._engine.play(
            url,
            start_ms=start_ms,
            options=[f":http-user-agent={CLIENT_NAME}"],
        )

    def _retry_with_proxy(self) -> bool:
        """切换播放源（代理 ↔ 直连）重试一次。"""
        if self._retried_stream or self._media_source is None:
            return False
        # 失败时再复查一次代理，避免用户中途关闭代理后仍卡在代理上
        self.ctx.proxy_manager.force_refresh()
        self._has_system_proxy = bool(self.ctx.proxy_manager.current())
        if self._has_system_proxy:
            # 系统代理生效时必须走代理，不能退回直连
            return False
        self._retried_stream = True
        self._using_proxy = not self._using_proxy
        self._playback_started = False
        self._speed_last_time = None
        self._speed_value = 0.0
        self.controls.set_speed("测速中…")
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.set_speed(None)
            self.loading_overlay.show()
            self.loading_overlay.raise_()
        log.info(
            "切换播放源重试：%s", "本机代理" if self._using_proxy else "直连"
        )
        self._start_stream(
            self._media_source.get("Id", ""),
            self._play_session_id,
            self._last_position_ms or self._start_position_ms,
        )
        return True

    def _title_text(self) -> str:
        item = self.item
        name = item.get("Name", "")
        series = item.get("SeriesName")
        if item.get("Type") == "Episode" and series:
            index = item.get("IndexNumber")
            season = item.get("ParentIndexNumber")
            prefix = f"{series} · S{season or 1:02d}E{index or 0:02d}" if season else series
            return f"{prefix} · {name}"
        return name

    def _update_title(self) -> None:
        self.setWindowTitle(f"播放 · {self._title_text()}")
        if hasattr(self, "title_bar"):
            self.title_bar.set_title(self._title_text())

    def _mpv_cache_seconds(self, source: Optional[dict] = None) -> int:
        """缓冲时长 = 配置字节数 / 影片大小 * 影片时长；不限时缓存整部影片。"""
        source = source or self._media_source or {}
        cache_bytes = self.ctx.config.mpv_cache_bytes
        size = int(source.get("Size") or 0)
        ticks = int(self.item.get("RunTimeTicks") or 0)
        duration = ticks / TICKS if ticks else self._duration_ms / 1000.0
        if cache_bytes <= 0:
            if duration > 0:
                return max(60, min(86400, int(duration)))
            return int(os.environ.get("EMBYQT_MPV_CACHE_SECS", "3600"))
        if size > 0 and duration > 0:
            seconds = int(cache_bytes * duration / size)
            return max(15, min(86400, seconds))
        return int(os.environ.get("EMBYQT_MPV_CACHE_SECS", "60"))

    # ---- 定时刷新 -------------------------------------------------------
    def _tick(self) -> None:
        if self._engine is None:
            return
        time_ms = self._engine.time_ms()
        length = self._engine.length_ms()
        if length > 0:
            self._duration_ms = length
        if not self._seeking and self._duration_ms > 0:
            ratio = max(0.0, min(1.0, time_ms / self._duration_ms))
            self.controls.seek.blockSignals(True)
            self.controls.seek.setValue(int(ratio * 1000))
            self.controls.seek.blockSignals(False)
        self.controls.current_time.setText(_fmt(time_ms))
        self.controls.total_time.setText(_fmt(self._duration_ms))
        self.controls.update_play_icon(self._engine.is_playing())
        if not self._playback_started:
            if self._native_video or not self._has_video:
                started = self._engine.is_playing() or time_ms > 0
            else:
                started = self.video.has_frame()
                if (
                    not started
                    and time_ms > 0
                    and time.monotonic() - self._loading_since > 6
                ):
                    # 视频流没有 frame 回调时的兜底，避免转圈永远不消失
                    started = True
            if started:
                self._mark_playback_started()
        self._update_speed()
        self._update_buffer()
        self._update_pause_overlay()
        if (
            self._engine.is_playing()
            and not self._error_shown
            and self.status_label.isVisible()
        ):
            self.status_label.hide()

        if self._backend == "mpv" and self._engine is not None:
            if self._engine.paused_for_cache() and not self._error_shown:
                self.status_label.setText("缓冲中…")
                self.status_label.show()
                self.status_label.raise_()
            elif self.status_label.text() == "缓冲中…":
                self.status_label.hide()

        self._last_position_ms = time_ms
        if time_ms - self._last_report_ms >= 10_000 and time_ms > 0:
            self._last_report_ms = time_ms
            if self._reporter is not None:
                self._reporter.progress(ms_to_ticks(time_ms), volume=self.volume)

    @staticmethod
    def _duration_text(ms: int) -> str:
        seconds = max(0, int(ms / 1000))
        if seconds >= 3600:
            return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _buffer_text(ahead_ms: int) -> str:
        ahead = max(0.0, ahead_ms / 1000.0)
        if ahead >= 60:
            return f"缓冲 {int(ahead // 60)}:{int(ahead % 60):02d}"
        if ahead >= 0.5:
            return f"缓冲 {ahead:.1f}s"
        return ""

    def _update_buffer(self) -> None:
        if self._duration_ms <= 0 or self._engine is None:
            self.controls.seek.clear_buffered()
            self.controls.set_buffer("")
            return
        if self._backend == "mpv":
            # 直接使用 libmpv 的缓存 API：
            # seekable-ranges 给出已缓存区间，cache-buffering-state 给出缓存百分比，
            # demuxer-cache-duration 给出缓存时长。
            ranges = self._engine.buffered_ranges()
            self.controls.seek.set_buffered_ranges(ranges)
            ahead = self._engine.buffer_ahead_ms()
            target = max(0, int(getattr(self._engine, "cache_secs", 60))) * 1000
            self.controls.set_buffer(
                f"缓存 {self._duration_text(ahead)} / {self._duration_text(target)}"
            )
            return
        if not self._using_proxy:
            self.controls.seek.clear_buffered()
            self.controls.set_buffer("")
            return
        ranges = self.ctx.proxy.windows_for(self.item.get("Id", ""))
        self.controls.seek.set_buffered_ranges(ranges)
        played = self.controls.seek.value() / 10.0
        # 只统计与播放位置连续的这一段缓冲，忽略文件末尾探测段
        containing = [
            end
            for start, end in ranges
            if start <= played + 0.5 and end > played
        ]
        end = max(containing, default=played)
        ahead = int(self._duration_ms * max(0.0, end - played) / 100.0)
        self.controls.set_buffer(self._buffer_text(ahead))

    def _on_frame_ready(self, _data=None, _width=None, _height=None, _pitch=None) -> None:
        if not self._playback_started:
            self._mark_playback_started()

    def _mark_playback_started(self) -> None:
        self._playback_started = True
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.hide()
        self._update_pause_overlay()

    def _update_speed(self) -> None:
        if self._error_shown:
            return
        if not self._using_proxy:
            self.controls.set_speed("直连")
            if getattr(self, "loading_overlay", None) is not None and self.loading_overlay.isVisible():
                self.loading_overlay.set_speed(None, direct=True)
            return
        now = time.monotonic()
        total = self.ctx.proxy.bytes_for(self.item.get("Id", ""))
        if self._speed_last_time is None:
            self._speed_last_time = now
            self._speed_last_bytes = total
            text = "测速中…" if total <= 0 else "0 B/s"
            self.controls.set_speed(text)
            if getattr(self, "loading_overlay", None) is not None and self.loading_overlay.isVisible():
                self.loading_overlay.set_speed(0.0 if total > 0 else None)
            return
        elapsed = now - self._speed_last_time
        if elapsed < 0.3:
            return
        delta = max(0, total - self._speed_last_bytes)
        instant = delta / elapsed
        self._speed_value = (
            instant if self._speed_value <= 0 else self._speed_value * 0.65 + instant * 0.35
        )
        self._speed_last_time = now
        self._speed_last_bytes = total
        text = LoadingOverlay._format_speed(self._speed_value)
        self.controls.set_speed(text)
        if getattr(self, "loading_overlay", None) is not None and self.loading_overlay.isVisible():
            self.loading_overlay.set_speed(self._speed_value)

    # ---- 控制 -----------------------------------------------------------
    def toggle_pause(self) -> None:
        if self._engine is None:
            return
        playing = self._engine.is_playing()
        self._engine.set_pause(playing)
        self.controls.update_play_icon(not playing)
        self._update_pause_overlay()
        log.debug("暂停" if not playing else "继续播放")
        if self._reporter is not None:
            self._reporter.progress(
                ms_to_ticks(self._engine.time_ms()), paused=playing, volume=self.volume
            )
        self._show_controls()

    def _seek_to(self, target_ms: int) -> None:
        if self._engine is None:
            return
        if not self._engine.is_seekable():
            self.status_label.setText("当前视频不支持跳转（媒体未提供索引）")
            self.status_label.show()
            self.status_label.raise_()
            self._show_controls()
            QTimer.singleShot(
                2500,
                lambda: None
                if self._error_shown or self._closing
                else self.status_label.hide(),
            )
            return
        self.status_label.hide()
        target = max(0, int(target_ms))
        ratio = (
            max(0.0, min(1.0, target / self._duration_ms))
            if self._duration_ms > 0
            else None
        )
        if self._backend == "mpv":
            self.controls.seek.clear_buffered()
            self.controls.set_buffer("")
        elif self._using_proxy and ratio is not None:
            buffered = self.ctx.proxy.begin_seek(
                self.item.get("Id", ""), ratio * 100.0
            )
            if not buffered:
                self.controls.seek.clear_buffered()
        self._engine.set_time(target)
        self._last_position_ms = target
        self._seeking = False
        if ratio is not None:
            self.controls.seek.blockSignals(True)
            self.controls.seek.setValue(int(ratio * 1000))
            self.controls.seek.blockSignals(False)
            self.controls.current_time.setText(_fmt(target))
        if self._reporter is not None:
            self._reporter.progress(ms_to_ticks(target), volume=self.volume)
        self._show_controls()

    def seek_relative(self, delta_ms: int) -> None:
        if self._engine is None:
            return
        target = max(0, min(self._duration_ms or 10 ** 9, self._engine.time_ms() + delta_ms))
        self._seek_to(target)

    def on_seek_started(self) -> None:
        self._seeking = True
        self._show_controls()

    def on_seek_finished(self) -> None:
        if self._engine is None:
            self._seeking = False
            return
        ratio = self.controls.seek.value() / 1000.0
        target = int((self._duration_ms or 0) * ratio)
        self._seek_to(target)

    def on_seek_value(self, value: int) -> None:
        if self._seeking and self._duration_ms > 0:
            self.controls.current_time.setText(_fmt(int(self._duration_ms * value / 1000)))

    def set_volume(self, value: int) -> None:
        self.volume = max(0, min(100, int(value)))
        self.ctx.config.volume = self.volume
        if self._engine is not None:
            self._engine.set_volume(self.volume)
        if self.volume > 0 and self._muted:
            self._muted = False
            if self._engine is not None:
                self._engine.set_mute(False)
            self.controls.update_volume_icon(False)
        if hasattr(self, "volume_popup"):
            self.volume_popup.set_value(self.volume)

    def change_volume(self, delta: int) -> None:
        self.set_volume(self.volume + delta)

    def show_volume_popup(self) -> None:
        self._hide_timer.stop()
        self._volume_hide_timer.stop()
        self.volume_popup.set_value(self.volume)
        self._position_volume_popup()
        self.volume_popup.show()
        self.volume_popup.raise_()

    def _schedule_hide_volume_popup(self) -> None:
        self._volume_hide_timer.start()

    def _cancel_hide_volume_popup(self) -> None:
        self._volume_hide_timer.stop()

    def _position_volume_popup(self) -> None:
        if not hasattr(self, "volume_popup") or not hasattr(self, "controls"):
            return
        button = self.controls.volume_button
        pos = button.mapTo(self, QPoint(0, 0))
        controls_pos = self.controls.mapTo(self, QPoint(0, 0))
        width, height = self.volume_popup.width(), self.volume_popup.height()
        x = pos.x() + button.width() // 2 - width // 2
        # 浮在整条控制栏上方，避免盖住进度条
        y = controls_pos.y() - height - 8
        x = max(8, min(self.width() - width - 8, x))
        y = max(8, min(self.height() - height - 8, y))
        self.volume_popup.move(x, y)

    def _hide_volume_popup(self) -> None:
        self.volume_popup.hide()
        if self._engine is not None and self._engine.is_playing():
            self._hide_timer.start()

    def toggle_mute(self) -> None:
        self._muted = not self._muted
        if self._engine is not None:
            self._engine.set_mute(self._muted)
        self.controls.update_volume_icon(self._muted)
        log.debug("静音：%s", self._muted)

    # ---- 全屏 / 最大化 / 控件显隐 ---------------------------------------
    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.controls.show()
            self._controls_visible = True
        else:
            self.showFullScreen()
            self._hide_timer.start()
        self._apply_window_state()
        self.video.setFocus()

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._apply_window_state()

    def _apply_window_state(self) -> None:
        if not hasattr(self, "player_frame"):
            return
        fullscreen = self.isFullScreen()
        maximized = self.isMaximized()
        flat = fullscreen or maximized
        # 播放器不保留外边距：否则浅色桌面上会像多了一圈白色边框
        self._outer.setContentsMargins(0, 0, 0, 0)
        self.player_frame.setProperty("flat", "true" if flat else "false")
        self.player_frame.setProperty("bordered", "false" if flat else "true")
        style = self.player_frame.style()
        style.unpolish(self.player_frame)
        style.polish(self.player_frame)
        self.player_frame.update()
        self.title_bar.setVisible(not fullscreen)
        self.title_bar.set_maximized(maximized)
        self.video.set_corner_radius(0 if flat else 16)
        self.controls.set_rounded(not flat)
        self.controls.update_fullscreen_icon(fullscreen)
        for handle in self._handles:
            handle.setVisible(not flat)
        if hasattr(self, "_hide_timer"):
            self._hide_timer.setInterval(2600 if fullscreen else 10_000)
        QTimer.singleShot(0, self._layout_media)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._apply_window_state)
        super().changeEvent(event)

    def _update_pause_overlay(self) -> None:
        if not hasattr(self, "pause_overlay"):
            return
        engine = self._engine
        paused = bool(
            engine is not None
            and self._media_source is not None
            and not self._loading
            and not self._error_shown
            and not self._closing
            and not engine.is_playing()
            and engine.time_ms() > 0
            and self._playback_started
        )
        self.pause_overlay.setVisible(paused)
        if paused:
            self.pause_overlay.raise_()

    def _on_mouse_moved(self) -> None:
        self._show_controls()
        if self.isFullScreen():
            self._hide_timer.start()

    def _show_controls(self) -> None:
        if not self.controls.isVisible():
            self.controls.show()
            self.controls.raise_()
        self._controls_visible = True
        self._hide_timer.setInterval(2600 if self.isFullScreen() else 10_000)
        if self._engine is not None and self._engine.is_playing() and not self._seeking:
            self._hide_timer.start()
        else:
            self._hide_timer.stop()

    def _maybe_hide_controls(self) -> None:
        if self._seeking or self._error_shown:
            return
        if hasattr(self, "volume_popup") and self.volume_popup.isVisible():
            return
        if self._engine is not None and self._engine.is_playing():
            if hasattr(self, "volume_popup"):
                self.volume_popup.hide()
            self.controls.hide()
            self._controls_visible = False

    # ---- 音轨 / 字幕 ----------------------------------------------------
    def show_subtitle_menu(self) -> None:
        if self._engine is None:
            return
        menu = QMenu(self)
        current = self._engine.current_subtitle_track()
        menu.addAction("关闭字幕", lambda: self._set_spu(-1))
        menu.addSeparator()
        for track_id, name in self._engine.subtitle_tracks():
            if track_id < 0:
                continue
            action = menu.addAction(("✓ " if track_id == current else "    ") + name)
            action.triggered.connect(lambda _checked=False, tid=track_id: self._set_spu(tid))
        external = self._external_subtitles()
        if external:
            menu.addSeparator()
            for index, display, url in external:
                action = menu.addAction(f"外挂 · {display}")
                action.triggered.connect(
                    lambda _checked=False, u=url: self._add_external_subtitle(u)
                )
        menu.exec(self.controls.subtitle_button.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _external_subtitles(self) -> List[tuple]:
        if not self._media_source:
            return []
        out = []
        media_source_id = self._media_source.get("Id", "")
        for stream in self._media_source.get("MediaStreams") or []:
            if stream.get("Type") != "Subtitle" or not stream.get("IsExternal"):
                continue
            index = stream.get("Index", 0)
            fmt = (stream.get("Codec") or "srt").lower()
            url = self.ctx.proxy.subtitle_url(self.item["Id"], media_source_id, index, fmt)
            out.append((index, stream.get("DisplayTitle") or f"字幕 {index}", url))
        return out

    def _set_spu(self, track_id: int) -> None:
        if self._engine is not None:
            self._engine.set_subtitle_track(track_id)
        self._show_controls()

    def _add_external_subtitle(self, url: str) -> None:
        if self._engine is not None:
            self._engine.add_external_subtitle(url, True)
        self._show_controls()

    def show_audio_menu(self) -> None:
        if self._engine is None:
            return
        menu = QMenu(self)
        current = self._engine.current_audio_track()
        for track_id, name in self._engine.audio_tracks():
            action = menu.addAction(("✓ " if track_id == current else "    ") + name)
            action.triggered.connect(
                lambda _checked=False, tid=track_id: self._engine and self._engine.set_audio_track(tid)
            )
        menu.exec(self.controls.audio_button.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    # ---- 结束 / 下一集 --------------------------------------------------
    def _on_ended(self) -> None:
        if self._closing or self._loading:
            return
        if hasattr(self, "pause_overlay"):
            self.pause_overlay.hide()
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.hide()
        runtime_ms = int(self.item.get("RunTimeTicks") or 0) // 10_000
        near_end = not runtime_ms or self._last_position_ms >= runtime_ms * 0.92
        if not near_end:
            # 网络中断会被 VLC 当作播放结束，这里避免误退出并给出提示。
            if self._retry_with_proxy():
                return
            self.status_label.setText("播放中断：网络连接被中断，请重试")
            self.status_label.show()
            return
        if self._reporter is not None:
            runtime = int(self.item.get("RunTimeTicks") or ms_to_ticks(self._duration_ms))
            self._reporter.stop(runtime, duration_ticks=runtime)
        if self._has_next():
            self._play_next()
        else:
            QTimer.singleShot(400, self.close)

    def _has_next(self) -> bool:
        return 0 <= self.index < len(self.playlist) - 1

    def _play_next(self) -> None:
        if not self._has_next():
            return
        self.index += 1
        next_item = self.playlist[self.index]
        self.media_source_id = ""
        if self._reporter is not None:
            self._reporter.shutdown()
            self._reporter = None
        self._last_report_ms = 0
        self._load(next_item, 0)

    # ---- 关闭 -----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        self._ui_timer.stop()
        if hasattr(self, "volume_popup"):
            self.volume_popup.hide()
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.hide()
        position = 0
        duration = self._duration_ms
        if self._engine is not None:
            position = self._engine.time_ms()
            self._engine.stop()
        if self._reporter is not None:
            self._reporter.stop(
                ms_to_ticks(position),
                duration_ticks=ms_to_ticks(duration),
            )
            self._reporter.shutdown()
            self._reporter = None
        if hasattr(self.video, "cleanup"):
            self.video.cleanup()
        if self._engine is not None:
            self._engine.release()
            self._engine = None
        self.closed.emit()
        super().closeEvent(event)
