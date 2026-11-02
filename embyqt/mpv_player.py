"""libmpv 播放内核与 Qt OpenGL 视频输出。"""

from __future__ import annotations

import ctypes
import locale
import os
import sys
from typing import List, Optional

# libmpv/FFmpeg 会检查环境和进程 locale；两者都固定为 C
os.environ["LC_NUMERIC"] = "C"
try:
    locale.setlocale(locale.LC_NUMERIC, "C")
except locale.Error:
    pass

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QOpenGLContext, QPainterPath, QRegion
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

try:  # pragma: no cover - depends on system libmpv
    import mpv
except Exception as exc:  # noqa: BLE001
    mpv = None
    _MPV_IMPORT_ERROR = str(exc)
else:
    _MPV_IMPORT_ERROR = ""


MPV_AVAILABLE = mpv is not None


def mpv_error() -> str:
    return _MPV_IMPORT_ERROR


class MpvEngine(QObject):
    """最小 libmpv 封装；视频通过 MpvRenderContext 输出到 QOpenGLWidget。"""

    ended = Signal()
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        if not MPV_AVAILABLE:
            raise RuntimeError(f"未安装 libmpv：{_MPV_IMPORT_ERROR}")
        try:
            cache_secs = int(os.environ.get("EMBYQT_MPV_CACHE_SECS", "60"))
        except ValueError:
            cache_secs = 60
        cache_secs = max(5, min(3600, cache_secs))
        self.cache_secs = cache_secs
        self._mpv = mpv.MPV(
            vo="libmpv",
            gpu_api="opengl",
            hwdec="no",
            audio_display="no",
            idle="yes",
            keep_open="no",
            terminal="no",
            input_default_bindings=False,
            input_vo_keyboard=False,
            cache="yes",
            cache_secs=cache_secs,
            cache_pause=True,
            cache_pause_wait=5,
            cache_pause_initial=True,
            demuxer_max_bytes=512 * 1024 * 1024,
            demuxer_readahead_secs=cache_secs,
            network_timeout=30,
        )
        self._render = None
        self._proc = None
        self._ended = False
        self._failed = False

        @self._mpv.event_callback("end-file")
        def _on_end_file(event) -> None:
            data = event.as_dict() if hasattr(event, "as_dict") else {}
            reason = str(data.get("reason", ""))
            if reason == "error" and not self._failed:
                self._failed = True
                self.failed.emit("播放失败：无法解码或打开媒体")

        @self._mpv.property_observer("eof-reached")
        def _on_eof(_name, value) -> None:
            if value and not self._ended:
                self._ended = True
                self.ended.emit()

    @property
    def mpv(self):
        return self._mpv

    # ---- 渲染 -----------------------------------------------------------
    def create_render_context(self, get_proc, update_cb) -> None:
        if self._render is not None:
            return
        self._proc = get_proc
        self._render = mpv.MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params={"get_proc_address": self._proc},
        )
        self._render.update_cb = update_cb

    def render(self, fbo: int, width: int, height: int) -> None:
        if self._render is None or width <= 0 or height <= 0:
            return
        self._render.render(
            opengl_fbo={"fbo": int(fbo), "w": int(width), "h": int(height)},
            flip_y=True,
        )
        self._render.report_swap()

    def free_render_context(self) -> None:
        if self._render is not None:
            try:
                self._render.free()
            except Exception:  # noqa: BLE001
                pass
            self._render = None

    # ---- 播放 -----------------------------------------------------------
    def play(self, url: str, start_ms: int = 0, options: Optional[List[str]] = None) -> None:
        self._ended = False
        self._failed = False
        opts = {}
        if start_ms > 0:
            opts["start"] = f"{start_ms / 1000.0:.3f}"
        # StreamProxy 已注入认证头；options 当前用于兼容调用方
        _ = options
        self._mpv.loadfile(url, "replace", **opts)
        self._mpv.pause = False

    def stop(self) -> None:
        try:
            self._mpv.stop()
        except Exception:  # noqa: BLE001
            pass

    def release(self) -> None:
        self.free_render_context()
        try:
            self._mpv.terminate()
        except Exception:  # noqa: BLE001
            pass

    # ---- 状态/控制 ------------------------------------------------------
    def set_pause(self, paused: bool) -> None:
        self._mpv.pause = bool(paused)

    def is_playing(self) -> bool:
        try:
            return bool(not self._mpv.idle_active and not self._mpv.pause)
        except Exception:  # noqa: BLE001
            return False

    def time_ms(self) -> int:
        value = self._mpv.time_pos
        return int(value * 1000) if value is not None and value >= 0 else 0

    def length_ms(self) -> int:
        value = self._mpv.duration
        return int(value * 1000) if value is not None and value > 0 else 0

    def set_time(self, ms: int) -> None:
        self._mpv.seek(max(0, int(ms)) / 1000.0, reference="absolute")

    def is_seekable(self) -> bool:
        return bool(self._mpv.seekable)

    def set_volume(self, volume: int) -> None:
        self._mpv.volume = max(0, min(100, int(volume)))

    def volume(self) -> int:
        value = self._mpv.volume
        return int(value) if value is not None else 80

    def set_mute(self, muted: bool) -> None:
        self._mpv.mute = bool(muted)

    def cache_buffering_state(self) -> int:
        """libmpv 的 cache-buffering-state（0–100）。"""
        try:
            value = self._mpv.cache_buffering_state
            if value is not None:
                return max(0, min(100, int(value)))
        except Exception:  # noqa: BLE001
            pass
        return 0

    def paused_for_cache(self) -> bool:
        """缓存不足导致自动暂停。"""
        try:
            return bool(self._mpv.paused_for_cache)
        except Exception:  # noqa: BLE001
            return False

    def buffer_ahead_ms(self) -> int:
        """libmpv 的 demuxer-cache-duration（当前缓存时长，秒）。"""
        try:
            value = self._mpv.demuxer_cache_duration
            if value is not None:
                return int(max(0.0, float(value)) * 1000)
            state = self._mpv.demuxer_cache_state or {}
            value = state.get("cache-duration")
            if value is not None:
                return int(max(0.0, float(value)) * 1000)
        except Exception:  # noqa: BLE001
            pass
        return 0

    def buffered_ranges(self) -> List[tuple]:
        """直接读取 demuxer-cache-state 的 seekable-ranges，转成百分比区间。"""
        try:
            state = self._mpv.demuxer_cache_state or {}
            duration = self._mpv.duration
            if not duration or duration <= 0:
                return []
            out = []
            for item in state.get("seekable-ranges") or []:
                start = max(0.0, float(item.get("start", 0.0)))
                end = max(0.0, float(item.get("end", 0.0)))
                if end <= start:
                    continue
                out.append(
                    (
                        min(100.0, start * 100.0 / duration),
                        min(100.0, end * 100.0 / duration),
                    )
                )
            if not out:
                # HTTP 流在早期可能还没有 seekable-ranges，
                # 用 API 的 cache-end 和当前播放位置兜底。
                end = state.get("cache-end")
                start = self._mpv.time_pos
                if end is not None and start is not None and float(end) > float(start):
                    out.append(
                        (
                            min(100.0, float(start) * 100.0 / duration),
                            min(100.0, float(end) * 100.0 / duration),
                        )
                    )
            return out
        except Exception:  # noqa: BLE001
            return []

    # ---- 轨道 -----------------------------------------------------------
    def _tracks(self, kind: str) -> List[tuple]:
        out = []
        for track in self._mpv.track_list or []:
            if track.get("type") != kind:
                continue
            track_id = track.get("id")
            name = track.get("title") or track.get("lang") or (
                f"{kind} {track_id}" if track_id is not None else ""
            )
            if track_id is not None:
                out.append((int(track_id), str(name)))
        return out

    def audio_tracks(self) -> List[tuple]:
        return self._tracks("audio")

    def set_audio_track(self, track_id: int) -> None:
        self._mpv.aid = int(track_id)

    def current_audio_track(self) -> int:
        value = self._mpv.aid
        return int(value) if isinstance(value, int) else -1

    def subtitle_tracks(self) -> List[tuple]:
        return self._tracks("sub")

    def set_subtitle_track(self, track_id: int) -> None:
        self._mpv.sid = int(track_id)

    def current_subtitle_track(self) -> int:
        value = self._mpv.sid
        return int(value) if isinstance(value, int) else -1

    def add_external_subtitle(self, url: str, select: bool = True) -> None:
        self._mpv.sub_add(url, flags="select" if select else "auto")

    def audio_delay(self) -> int:
        return int((self._mpv.audio_delay or 0) * 1_000_000)

    def subtitle_delay(self) -> int:
        return int((self._mpv.sub_delay or 0) * 1_000_000)

    def set_subtitle_delay(self, microseconds: int) -> None:
        self._mpv.sub_delay = int(microseconds) / 1_000_000.0

    def snapshot(self, path: str) -> int:
        try:
            self._mpv.screenshot_to_file(path)
            return 0
        except Exception:  # noqa: BLE001
            return -1


class MpvVideoSurface(QOpenGLWidget):
    """libmpv render API 的 Qt OpenGL 画布。"""

    clicked = Signal(float)
    double_clicked = Signal()
    mouse_moved = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._engine: Optional[MpvEngine] = None
        self._proc = None
        self._has_frame = False
        self._corner_radius = 16
        self._pressed = False
        self._pending_click_ratio = 0.0
        self._suppress_next_click = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(max(220, QApplication.doubleClickInterval() + 20))
        self._click_timer.timeout.connect(self._emit_click)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def bind_engine(self, engine: MpvEngine) -> None:
        self._engine = engine
        if self.isValid():
            self._ensure_context()

    def has_frame(self) -> bool:
        return self._has_frame

    def clear_frame(self) -> None:
        self._has_frame = False
        self.update()

    def set_frame(self, *_args) -> None:
        return

    def _ensure_context(self) -> None:
        if self._engine is None or self._proc is not None:
            return
        self.makeCurrent()
        try:
            def proc(_ctx, name):
                ctx = QOpenGLContext.currentContext()
                addr = ctx.getProcAddress(name) if ctx is not None else 0
                return int(addr) if addr else 0
            self._proc = mpv.MpvGlGetProcAddressFn(proc)
            self._engine.create_render_context(self._proc, self.update)
        finally:
            self.doneCurrent()

    def initializeGL(self) -> None:  # noqa: N802
        self._ensure_context()

    def paintGL(self) -> None:  # noqa: N802
        if self._engine is None:
            return
        dpr = self.devicePixelRatioF()
        self._engine.render(
            self.defaultFramebufferObject(),
            int(self.width() * dpr),
            int(self.height() * dpr),
        )
        if not self._has_frame:
            self._has_frame = True

    def resizeGL(self, _width: int, _height: int) -> None:  # noqa: N802
        self.update()

    def set_corner_radius(self, radius: int) -> None:
        self._corner_radius = int(radius)
        self._apply_mask()
        self.update()

    def _apply_mask(self) -> None:
        radius = float(self._corner_radius + 4)
        if radius <= 4 or self.width() <= 0 or self.height() <= 0:
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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_mask()

    def cleanup(self) -> None:
        if self._engine is not None:
            self._engine.free_render_context()
        self._proc = None

    def _emit_click(self) -> None:
        self.clicked.emit(self._pending_click_ratio)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.mouse_moved.emit()
        super().mouseMoveEvent(event)

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
