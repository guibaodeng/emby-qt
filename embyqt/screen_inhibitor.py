"""播放期间阻止系统空闲息屏/锁屏。"""

from __future__ import annotations

import ctypes
import os
import shutil
import signal
import subprocess
import sys
from typing import Optional

try:
    from PySide6.QtDBus import QDBusConnection, QDBusMessage
except ImportError:  # Windows/macOS 的 Qt 构建可能不包含 QtDBus
    QDBusConnection = QDBusMessage = None


class ScreenInhibitor:
    """按播放状态获取/释放系统空闲抑制；acquire/release 均幂等。"""

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._cookie: Optional[int] = None
        self._dbus_service: Optional[str] = None
        self._dbus_path: Optional[str] = None
        self._dbus_interface: Optional[str] = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def acquire(self) -> None:
        if self._active:
            return
        self._active = True
        try:
            if sys.platform.startswith("linux"):
                self._acquire_linux()
            elif sys.platform == "win32":
                self._acquire_windows()
            elif sys.platform == "darwin":
                self._acquire_macos()
        except Exception:
            # 锁屏抑制失败不应影响播放
            pass

    def release(self) -> None:
        if not self._active:
            return
        self._active = False
        if self._process is not None:
            process, self._process = self._process, None
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    process.terminate()
                process.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
        if self._cookie is not None:
            cookie, self._cookie = self._cookie, None
            service = self._dbus_service
            path = self._dbus_path
            interface = self._dbus_interface
            self._dbus_service = self._dbus_path = self._dbus_interface = None
            if service and path and interface:
                self._release_dbus(service, path, interface, cookie)
        if sys.platform == "win32":
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass

    # ---- Linux ---------------------------------------------------------
    def _acquire_linux(self) -> None:
        if shutil.which("systemd-inhibit"):
            try:
                self._process = subprocess.Popen(
                    [
                        "systemd-inhibit",
                        "--what=idle:sleep",
                        "--who=WhalePlayer",
                        "--why=正在播放视频",
                        "--mode=block",
                        "sleep",
                        "infinity",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                # systemd 不可用时进程可能立刻退出，继续尝试 DBus。
                if self._process.poll() is None:
                    return
                self._process = None
            except OSError:
                self._process = None

        # Freedesktop ScreenSaver 是 GNOME/KDE 等桌面通用接口。
        if self._dbus_inhibit(
            "org.freedesktop.ScreenSaver",
            "/org/freedesktop/ScreenSaver",
            "org.freedesktop.ScreenSaver",
            ["WhalePlayer", "正在播放视频"],
        ):
            return
        # GNOME SessionManager 作为后备；8 表示 idle inhibit。
        self._dbus_inhibit(
            "org.gnome.SessionManager",
            "/org/gnome/SessionManager",
            "org.gnome.SessionManager",
            ["WhalePlayer", 0, "正在播放视频", 8],
        )

    def _dbus_inhibit(self, service: str, path: str, interface: str, args: list) -> bool:
        if QDBusConnection is None or QDBusMessage is None:
            return False
        connection = QDBusConnection.sessionBus()
        if not connection.isConnected():
            return False
        message = QDBusMessage.createMethodCall(service, path, interface, "Inhibit")
        message.setArguments(args)
        reply = connection.call(message)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            return False
        values = reply.arguments()
        if not values:
            return False
        try:
            self._cookie = int(values[0])
        except (TypeError, ValueError):
            return False
        self._dbus_service = service
        self._dbus_path = path
        self._dbus_interface = interface
        return True

    def _release_dbus(self, service: str, path: str, interface: str, cookie: int) -> None:
        if shutil.which("dbus-send"):
            try:
                subprocess.run(
                    [
                        "dbus-send",
                        "--session",
                        f"--dest={service}",
                        path,
                        f"{interface}.UnInhibit",
                        f"uint32:{cookie}",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                return
            except OSError:
                pass
        # 没有 dbus-send 时尝试用 busctl（签名 u = uint32）。
        if shutil.which("busctl"):
            try:
                subprocess.run(
                    [
                        "busctl",
                        "--user",
                        "call",
                        service,
                        path,
                        interface,
                        "UnInhibit",
                        "u",
                        str(cookie),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except OSError:
                pass

    # ---- Windows -------------------------------------------------------
    def _acquire_windows(self) -> None:
        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(
            0x80000000 | 0x00000001 | 0x00000002
        )

    # ---- macOS ---------------------------------------------------------
    def _acquire_macos(self) -> None:
        caffeinate = shutil.which("caffeinate") or "/usr/bin/caffeinate"
        self._process = subprocess.Popen(
            [caffeinate, "-d", "-i"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.release()
        except Exception:
            pass
