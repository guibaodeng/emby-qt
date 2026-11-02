"""播放内核：libVLC 封装 + 播放进度上报。"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Signal

from .api import TICKS, EmbyClient

try:  # pragma: no cover - 取决于运行环境
    import vlc
except Exception as exc:  # noqa: BLE001
    vlc = None
    _VLC_IMPORT_ERROR = str(exc)
else:
    _VLC_IMPORT_ERROR = ""


VLC_AVAILABLE = vlc is not None


def vlc_error() -> str:
    return _VLC_IMPORT_ERROR


class VlcEngine(QObject):
    """对 libvlc MediaPlayer 的最小封装。"""

    ended = Signal()
    failed = Signal(str)
    # 内存渲染（Wayland 等无法嵌入原生窗口时使用）：
    # (frame_bytes, width, height, pitch)
    frame_ready = Signal(bytes, int, int, int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        if not VLC_AVAILABLE:
            raise RuntimeError(f"未安装 python-vlc：{_VLC_IMPORT_ERROR}")
        args = [
            "--no-video-title-show",
            "--quiet",
            "--no-snapshot-preview",
            "--network-caching=1500",
            "--file-caching=1000",
        ]
        extra = os.environ.get("EMBYQT_VLC_ARGS", "").split()
        if extra:
            args.extend(extra)
        self._instance = vlc.Instance(args)
        if self._instance is None:
            raise RuntimeError("libVLC 初始化失败")
        self._player = self._instance.media_player_new()
        self._player.video_set_mouse_input(False)
        self._player.video_set_key_input(False)
        self._media = None
        self._slaves: List = []
        self._vmem_refs = None
        self._vmem_buffer = None
        self._events = self._player.event_manager()
        self._events.event_attach(vlc.EventType.MediaPlayerEndReached, self._emit_ended)
        self._events.event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self._emit_failed
        )

    # ---- 事件（由 VLC 线程触发，接收方需用队列连接） ---------------------
    def _emit_ended(self, _event) -> None:
        self.ended.emit()

    def _emit_failed(self, _event) -> None:
        self.failed.emit("播放失败：无法解码或打开媒体")

    # ---- 控制 -----------------------------------------------------------
    def attach(self, win_id: int) -> None:
        """把视频输出绑定到 Qt 控件的原生窗口。

        Linux/X11 必须使用 ``set_xwindow``：``set_hwnd`` 是 Windows 路径，
        在 X11 上会把 vout 解析成 "none"，表现为有声音没画面。
        """
        if sys.platform.startswith("linux"):
            self._player.set_xwindow(int(win_id))
        elif sys.platform == "darwin":
            # macOS 是 NSView，不是 Windows 的 HWND
            self._player.set_nsobject(int(win_id))
        else:
            self._player.set_hwnd(int(win_id))

    def attach_vmem(self, width: int, height: int) -> None:
        """把视频渲染到内存（RV32），再交给 Qt 绘制。

        Wayland 下 libVLC 3 无法嵌入原生窗口，用这条路可以保持单窗口体验。
        """
        width = max(2, int(width) - int(width) % 2)
        height = max(2, int(height) - int(height) % 2)
        pitch = width * 4
        self._vmem_buffer = (ctypes.c_ubyte * (pitch * height))()
        self._player.video_set_format("RV32", width, height, pitch)

        buffer = self._vmem_buffer

        @vlc.CallbackDecorators.VideoLockCb
        def _lock(_opaque, planes):
            planes[0] = ctypes.cast(buffer, ctypes.c_void_p)

        @vlc.CallbackDecorators.VideoUnlockCb
        def _unlock(_opaque, _picture, _planes):
            return None

        @vlc.CallbackDecorators.VideoDisplayCb
        def _display(_opaque, _picture):
            self.frame_ready.emit(bytes(buffer), width, height, pitch)

        # 回调对象必须保持引用，否则会被 GC
        self._vmem_refs = (_lock, _unlock, _display)
        self._player.video_set_callbacks(_lock, _unlock, _display, None)

    def snapshot(self, path: str) -> int:
        """抓取当前视频帧（调试用），成功返回 0。"""
        return self._player.video_take_snapshot(0, path, 0, 0)

    def play(self, url: str, start_ms: int = 0, options: Optional[List[str]] = None) -> None:
        media = self._instance.media_new(url)
        for option in options or []:
            media.add_option(option)
        if start_ms > 0:
            media.add_option(f":start-time={start_ms / 1000.0:.1f}")
        self._media = media
        self._player.set_media(media)
        self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def release(self) -> None:
        try:
            self._player.stop()
            self._player.release()
        except Exception:  # noqa: BLE001 - 释放阶段忽略异常
            pass

    def set_pause(self, paused: bool) -> None:
        self._player.set_pause(1 if paused else 0)

    def is_playing(self) -> bool:
        return bool(self._player.is_playing())

    def time_ms(self) -> int:
        value = self._player.get_time()
        return int(value) if value is not None and value >= 0 else 0

    def length_ms(self) -> int:
        value = self._player.get_length()
        return int(value) if value is not None and value > 0 else 0

    def set_time(self, ms: int) -> None:
        self._player.set_time(int(max(0, ms)))

    def is_seekable(self) -> bool:
        return bool(self._player.is_seekable())

    def set_volume(self, volume: int) -> None:
        self._player.audio_set_volume(int(max(0, min(100, volume))))

    def volume(self) -> int:
        value = self._player.audio_get_volume()
        return int(value) if value is not None and value >= 0 else 80

    def set_mute(self, muted: bool) -> None:
        self._player.audio_set_mute(bool(muted))

    # ---- 轨道 -----------------------------------------------------------
    def audio_tracks(self) -> List[tuple]:
        out = []
        for track_id, name in self._player.audio_get_track_description() or []:
            if track_id < 0:
                continue
            out.append((track_id, _decode(name)))
        return out

    def set_audio_track(self, track_id: int) -> None:
        self._player.audio_set_track(int(track_id))

    def current_audio_track(self) -> int:
        value = self._player.audio_get_track()
        return int(value) if value is not None else -1

    def subtitle_tracks(self) -> List[tuple]:
        out = []
        for track_id, name in self._player.video_get_spu_description() or []:
            out.append((track_id, _decode(name)))
        return out

    def set_subtitle_track(self, track_id: int) -> None:
        self._player.video_set_spu(int(track_id))

    def current_subtitle_track(self) -> int:
        value = self._player.video_get_spu()
        return int(value) if value is not None else -1

    def add_external_subtitle(self, url: str, select: bool = True) -> None:
        media = self._instance.media_new(url)
        self._slaves.append(media)
        self._player.add_slave(media, select)

    def audio_delay(self) -> int:
        value = self._player.audio_get_delay()
        return int(value or 0)

    def subtitle_delay(self) -> int:
        value = self._player.video_get_spu_delay()
        return int(value or 0)

    def set_subtitle_delay(self, microseconds: int) -> None:
        self._player.video_set_spu_delay(int(microseconds))


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


class PlaybackReporter:
    """后台串行上报播放状态，避免阻塞界面。"""

    def __init__(
        self,
        client: EmbyClient,
        item_id: str,
        media_source_id: str,
        play_session_id: str,
        on_played: Optional[Callable[[], None]] = None,
    ) -> None:
        self.client = client
        self.item_id = item_id
        self.media_source_id = media_source_id
        self.play_session_id = play_session_id
        self.on_played = on_played
        self._queue: "queue.Queue" = queue.Queue()
        self._thread = threading.Thread(
            target=self._loop, name="embyqt-reporter", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                job()
            except Exception:  # noqa: BLE001 - 上报失败不影响播放
                pass

    def _submit(self, job: Callable[[], None]) -> None:
        self._queue.put(job)

    # ---- 生命周期 -------------------------------------------------------
    def start(self, position_ticks: int) -> None:
        self._submit(
            lambda: self.client.report_start(
                self.item_id,
                self.media_source_id,
                self.play_session_id,
                position_ticks,
            )
        )

    def progress(self, position_ticks: int, paused: bool = False, volume: int = 100) -> None:
        self._submit(
            lambda: self.client.report_progress(
                self.item_id,
                self.media_source_id,
                self.play_session_id,
                position_ticks,
                paused=paused,
                volume=volume,
            )
        )

    def stop(self, position_ticks: int, duration_ticks: int = 0) -> None:
        played = bool(duration_ticks and position_ticks >= duration_ticks * 0.9)

        def _stop() -> None:
            self.client.report_stop(
                self.item_id,
                self.media_source_id,
                self.play_session_id,
                position_ticks,
            )
            if played:
                self.client.set_played(self.item_id, True)
                if self.on_played is not None:
                    pass

        self._submit(_stop)

    def shutdown(self) -> None:
        self._queue.put(None)


def ms_to_ticks(ms: int) -> int:
    return int(ms) * 10_000  # 1ms = 10 000 ticks


def ticks_to_ms(ticks: int) -> int:
    return int(ticks) // 10_000
