"""程序入口：登录 → 主窗口 → 退出登录后可再次登录。"""

from __future__ import annotations

import ctypes
import locale
import os
import sys
from typing import Optional

# libmpv/FFmpeg 要求 LC_NUMERIC=C；必须在导入 mpv/创建 MPV 之前设置
os.environ["LC_NUMERIC"] = "C"
try:
    locale.setlocale(locale.LC_NUMERIC, "C")
except locale.Error:
    pass

from PySide6.QtWidgets import QApplication, QDialog

from . import APP_NAME, __version__
from .api import EmbyClient, EmbyError
from .config import Config
from .context import AppContext
from . import logging_setup
from .net import ProxyManager
from .streamproxy import StreamProxy
from .ui.branding import app_icon
from .ui.login import LoginDialog
from .ui.mainwindow import MainWindow
from .ui import theme
from .ui.widgets import set_wheel_mode


def _restore_client(config: Config, proxy_manager=None) -> Optional[EmbyClient]:
    """用已保存的 token 恢复会话。

    这里**不做网络请求**：先立刻出界面，登录态由主窗口在后台校验，
    否则服务器响应慢时会出现「执行 run.sh 后一直没反应」。
    """
    if not (config.token and config.user_id):
        return None
    return EmbyClient(
        config.server,
        config.device_id,
        token=config.token,
        user={"Id": config.user_id, "Name": config.user_name},
        proxy_manager=proxy_manager,
    )


def _load_xcb_cursor() -> bool:
    """确保 libxcb-cursor 可被 Qt 的 xcb 后端加载（系统缺失时用仓库内副本）。"""
    try:
        ctypes.CDLL("libxcb-cursor.so.0", mode=ctypes.RTLD_GLOBAL)
        return True
    except OSError:
        pass
    vendor = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "vendor",
        "lib",
        "libxcb-cursor.so.0",
    )
    if os.path.exists(vendor):
        try:
            ctypes.CDLL(vendor, mode=ctypes.RTLD_GLOBAL)
            return True
        except OSError:
            return False
    return False


def _silence_qt_noise() -> None:
    """关闭 Qt Wayland 输入法在切换焦点时刷屏的警告。"""
    rule = "qt.qpa.wayland.textinput=false"
    current = os.environ.get("QT_LOGGING_RULES", "")
    if rule not in current:
        os.environ["QT_LOGGING_RULES"] = f"{current};{rule}" if current else rule


def _configure_qt_platform() -> None:
    """默认使用 Qt 原生平台，保证窗口一定可见。

    这台机器上 ``DISPLAY=:0`` 是一个不显示窗口的 X 服务（``isExposed()`` 为
    False），强制 xcb 会导致「程序在跑但看不到界面」。因此仅在显式设置
    ``EMBYQT_FORCE_X11=1`` 时才切到 XWayland。
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("EMBYQT_FORCE_X11") != "1":
        return
    if not sys.platform.startswith("linux"):
        return
    if not (os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY")):
        return
    if not _load_xcb_cursor():
        return
    os.environ["QT_QPA_PLATFORM"] = "xcb"


def main() -> int:
    _configure_qt_platform()
    _silence_qt_noise()
    config = Config()
    set_wheel_mode(config.wheel_mode)
    logging_setup.configure(config.logging_enabled, config.logging_level)
    log = logging_setup.get_logger("main")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} {__version__}")
    app.setWindowIcon(app_icon())

    mode = config.theme
    env_mode = os.environ.get("EMBYQT_THEME", "").strip().lower()
    if env_mode in ("dark", "light", "system"):
        mode = env_mode
    scheme = theme.apply_preference(app, mode)
    log.info(
        "启动 EmbyQt %s，平台=%s，主题偏好=%s（当前 %s），日志级别=%s",
        __version__, app.platformName(), mode, scheme, config.logging_level,
    )
    print(f"[EmbyQt] 显示后端：{app.platformName()}", flush=True)
    print(f"[EmbyQt] 主题：{'浅色' if scheme == 'light' else '深色'}", flush=True)
    if app.platformName() == "xcb" and os.environ.get("WAYLAND_DISPLAY"):
        print(
            "[EmbyQt] 提示：当前是 Wayland 会话却用了 xcb，"
            "如果窗口不可见请执行 unset QT_QPA_PLATFORM 后重试",
            flush=True,
        )

    proxy_manager = ProxyManager()
    proxy_config = proxy_manager.current()
    print(
        f"[EmbyQt] 网络代理：{proxy_config.describe() if proxy_config else '未使用代理'}"
        "（每次请求前会复查）",
        flush=True,
    )

    login_message = ""
    while True:
        client = _restore_client(config, proxy_manager)
        if client is None:
            print("[EmbyQt] 打开登录窗口", flush=True)
            log.info("打开登录窗口")
            dialog = LoginDialog(config, message=login_message, proxy_manager=proxy_manager)
            login_message = ""
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.client is None:
                return 0
            client = dialog.client
            log.info("登录成功：%s @ %s", client.user_name or "—", client.server)

        proxy = StreamProxy(client)
        proxy.start()
        ctx = AppContext(config, client, proxy, proxy_manager=proxy_manager)
        window = MainWindow(ctx)

        state = {"logout": False, "expired": False}

        def on_logout() -> None:
            state["logout"] = True
            window.close()

        def on_expired() -> None:
            state["expired"] = True
            window.close()

        window.logout_requested.connect(on_logout)
        window.session_expired.connect(on_expired)
        window.show()
        window.raise_()
        window.activateWindow()
        print(f"[EmbyQt] 已打开主窗口：{config.server}", flush=True)
        log.info("打开主窗口：%s", config.server)
        result = app.exec()
        proxy.stop()

        if state["expired"]:
            log.warning("登录已过期，返回登录窗口")
            config.clear_session()
            login_message = "登录已过期，请重新登录"
            continue
        if not state["logout"]:
            return result
        log.info("退出登录，返回登录窗口")
        config.clear_session()


if __name__ == "__main__":
    sys.exit(main())
