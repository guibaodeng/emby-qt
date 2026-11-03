"""设置页。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, logging_setup
from ..async_task import run_async
from ..context import AppContext
from . import theme
from .icons import icon
from .widgets import RoundedComboBox, make_button, set_wheel_mode


class SettingsPage(QWidget):
    logout_requested = Signal()
    relogin_requested = Signal()
    back_requested = Signal()

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()
        self._load_server_info()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 24, 30, 30)
        root.setSpacing(18)

        self.back_button = make_button("返回")
        self.back_button.setIcon(icon("arrow_back", 18, theme.TEXT))
        self.back_button.setIconSize(QSize(18, 18))
        self.back_button.clicked.connect(self.back_requested)
        root.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignLeft)
        title = QLabel("设置")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(24, 22, 24, 22)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(12)

        self._rows = {}
        for row, (key, label) in enumerate(
            [
                ("server", "服务器"),
                ("server_name", "服务器名称"),
                ("user", "当前用户"),
                ("proxy", "系统代理"),
                ("device", "设备 ID"),
                ("version", "客户端版本"),
            ]
        ):
            name = QLabel(label)
            name.setObjectName("settingsName")
            value = QLabel("—")
            value.setObjectName("settingsValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self._rows[key] = value
        grid.setColumnStretch(1, 1)
        root.addWidget(card)

        # ---- 外观与日志 ----
        prefs = QFrame()
        prefs.setObjectName("card")
        prefs_grid = QGridLayout(prefs)
        prefs_grid.setContentsMargins(24, 22, 24, 22)
        prefs_grid.setHorizontalSpacing(28)
        prefs_grid.setVerticalSpacing(14)

        theme_name = QLabel("主题")
        theme_name.setObjectName("settingsName")
        self.theme_combo = RoundedComboBox()
        for label, value in (("跟随系统", "system"), ("深色", "dark"), ("浅色", "light")):
            self.theme_combo.addItem(label, value)
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(self.ctx.config.theme))
        )
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        prefs_grid.addWidget(theme_name, 0, 0)
        prefs_grid.addWidget(self.theme_combo, 0, 1)

        log_name = QLabel("日志")
        log_name.setObjectName("settingsName")
        self.logging_check = QCheckBox("启用日志")
        self.logging_check.setChecked(self.ctx.config.logging_enabled)
        self.logging_check.toggled.connect(self._on_logging_toggled)
        prefs_grid.addWidget(log_name, 1, 0)
        prefs_grid.addWidget(self.logging_check, 1, 1)

        level_name = QLabel("日志级别")
        level_name.setObjectName("settingsName")
        self.level_combo = RoundedComboBox()
        self.level_combo.addItems(["INFO", "DEBUG"])
        self.level_combo.setCurrentText(self.ctx.config.logging_level)
        self.level_combo.setEnabled(self.ctx.config.logging_enabled)
        self.level_combo.currentTextChanged.connect(self._on_level_changed)
        prefs_grid.addWidget(level_name, 2, 0)
        prefs_grid.addWidget(self.level_combo, 2, 1)

        wheel_name = QLabel("鼠标滚轮")
        wheel_name.setObjectName("settingsName")
        self.wheel_combo = RoundedComboBox()
        self.wheel_combo.addItem("页面上下滚动", "page")
        self.wheel_combo.addItem("分类左右滚动", "row")
        self.wheel_combo.setCurrentIndex(
            max(0, self.wheel_combo.findData(self.ctx.config.wheel_mode))
        )
        self.wheel_combo.currentIndexChanged.connect(self._on_wheel_mode_changed)
        prefs_grid.addWidget(wheel_name, 3, 0)
        prefs_grid.addWidget(self.wheel_combo, 3, 1)

        buffer_name = QLabel("缓冲大小")
        buffer_name.setObjectName("settingsName")
        self.buffer_combo = RoundedComboBox()
        for label, value in (
            ("100 M", 100 * 1024 ** 2),
            ("500 M", 500 * 1024 ** 2),
            ("1 G", 1024 ** 3),
            ("2 G", 2 * 1024 ** 3),
            ("不限", 0),
        ):
            self.buffer_combo.addItem(label, value)
        self.buffer_combo.setCurrentIndex(
            max(0, self.buffer_combo.findData(self.ctx.config.mpv_cache_bytes))
        )
        self.buffer_combo.currentIndexChanged.connect(self._on_buffer_size_changed)
        prefs_grid.addWidget(buffer_name, 4, 0)
        prefs_grid.addWidget(self.buffer_combo, 4, 1)

        log_path_label = QLabel(logging_setup.log_file_path())
        log_path_label.setObjectName("settingsNote")
        log_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        log_path_label.setWordWrap(True)
        prefs_grid.addWidget(QLabel("日志文件"), 5, 0)
        prefs_grid.addWidget(log_path_label, 5, 1)
        prefs_grid.setColumnStretch(1, 1)
        root.addWidget(prefs)

        self._rows["server"].setText(self.ctx.client.server)
        self._rows["user"].setText(self.ctx.client.user_name or "—")
        self._refresh_proxy()
        self._rows["device"].setText(self.ctx.config.device_id)
        self._rows["version"].setText(f"WhalePlayer {__version__}")

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        cache_button = make_button("清除图片缓存")
        cache_button.clicked.connect(self._clear_cache)
        buttons.addWidget(cache_button)

        # 重新登录 / 退出登录按钮暂时隐藏，保留信号和回调以便恢复。
        # relogin_button = make_button("重新登录")
        # relogin_button.clicked.connect(self.relogin_requested)
        # buttons.addWidget(relogin_button)
        #
        # logout_button = make_button("退出登录")
        # logout_button.clicked.connect(self.logout_requested)
        # buttons.addWidget(logout_button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        note = QLabel(
            "播放说明：账号未开启转码权限，客户端仅使用直连播放（DirectPlay）。\n"
            "媒体请求通过本机回环代理转发，以确保带上服务器要求的客户端标识。"
        )
        note.setObjectName("settingsNote")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch(1)

    def _on_theme_changed(self) -> None:
        mode = self.theme_combo.currentData() or "system"
        self.ctx.config.theme = mode
        scheme = theme.apply_preference(QApplication.instance(), mode)
        logging_setup.get_logger("settings").info("主题偏好已切换：%s（当前 %s）", mode, scheme)

    def _on_buffer_size_changed(self) -> None:
        value = self.buffer_combo.currentData()
        self.ctx.config.mpv_cache_bytes = int(value if value is not None else 500 * 1024 ** 2)

    def _on_wheel_mode_changed(self) -> None:
        mode = self.wheel_combo.currentData() or "page"
        self.ctx.config.wheel_mode = mode
        set_wheel_mode(mode)

    def _on_logging_toggled(self, enabled: bool) -> None:
        self.ctx.config.logging_enabled = enabled
        self.level_combo.setEnabled(enabled)
        logging_setup.configure(enabled, self.ctx.config.logging_level)

    def _on_level_changed(self, level: str) -> None:
        if not level:
            return
        self.ctx.config.logging_level = level
        if self.ctx.config.logging_enabled:
            logging_setup.configure(True, level)

    def _refresh_proxy(self) -> None:
        self._rows["proxy"].setText(self.ctx.proxy_manager.describe())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.ctx.proxy_manager.force_refresh()
        self._refresh_proxy()

    def _load_server_info(self) -> None:
        run_async(
            self.ctx.client.server_info,
            on_done=self._on_info,
            on_error=lambda _m: None,
        )

    def _on_info(self, info: dict) -> None:
        self._rows["server_name"].setText(
            f"{info.get('ServerName', '—')} · Emby {info.get('Version', '')}"
        )

    def _clear_cache(self) -> None:
        self.ctx.images.clear_memory()
        self.ctx.images.clear_disk()
