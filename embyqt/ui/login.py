"""登录窗口。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from urllib.parse import urlsplit

from ..api import EmbyClient, EmbyError, build_server_url, normalize_server
from ..async_task import run_async
from ..config import Config
from ..logging_setup import get_logger
from ..net import ProxyManager
from .branding import app_icon
from .titlebar import TitleBar
from .widgets import make_button


class LoginDialog(QDialog):
    def __init__(
        self,
        config: Config,
        parent: Optional[QWidget] = None,
        message: str = "",
        proxy_manager: Optional[ProxyManager] = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.proxy_manager = proxy_manager
        self.client: Optional[EmbyClient] = None
        self._busy = False

        self.setObjectName("loginDialog")
        self.setWindowTitle("登录 · WhalePlayer")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(456)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        frame = QFrame()
        frame.setObjectName("loginFrame")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(frame)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        title_bar = TitleBar(
            "登录 · WhalePlayer",
            app_icon(),
            show_minimize=False,
            show_maximize=False,
            parent=frame,
        )
        title_bar.close_requested.connect(self.reject)
        frame_layout.addWidget(title_bar)

        body = QWidget()
        frame_layout.addWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(36, 18, 36, 28)
        root.setSpacing(14)

        logo = QLabel()
        logo.setPixmap(app_icon(76).pixmap(76, 76))
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(logo)

        title = QLabel("WhalePlayer")
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(title)

        subtitle = QLabel("连接你的 Emby 媒体服务器")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle.setObjectName("loginSubtitle")
        root.addWidget(subtitle)

        root.addSpacing(8)

        root.addWidget(self._field_label("服务器地址 / 端口"))
        server_row = QHBoxLayout()
        server_row.setSpacing(10)
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("https://emby.example.com")
        server_row.addWidget(self.server_edit, 1)
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("端口")
        self.port_edit.setFixedWidth(88)
        self.port_edit.setToolTip("留空则使用默认端口（https=443，http=80）")
        server_row.addWidget(self.port_edit)
        root.addLayout(server_row)
        self._load_server_fields(config.server)

        self.server_hint = QLabel("")
        self.server_hint.setObjectName("serverHint")
        root.addWidget(self.server_hint)

        root.addWidget(self._field_label("用户名"))
        self.user_edit = QLineEdit(config.last_user_id)
        self.user_edit.setPlaceholderText("用户名")
        root.addWidget(self.user_edit)

        root.addWidget(self._field_label("密码"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("密码")
        root.addWidget(self.password_edit)

        self.remember_box = QCheckBox("记住登录状态")
        self.remember_box.setChecked(config.remember)
        root.addWidget(self.remember_box)

        self.error_label = QLabel("")
        self.error_label.setObjectName("errorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        self.login_button = make_button("登  录", "primary")
        self.login_button.setMinimumHeight(40)
        self.login_button.clicked.connect(self._do_login)
        root.addWidget(self.login_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusText")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.status_label)

        self.server_edit.editingFinished.connect(self._on_server_edited)
        self.port_edit.editingFinished.connect(self._on_server_edited)
        self.password_edit.returnPressed.connect(self._do_login)
        self.user_edit.returnPressed.connect(lambda: self.password_edit.setFocus())
        if message:
            self._show_error(message)
        QTimer.singleShot(150, self._probe_server)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        screen = self.screen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self.raise_()
        self.activateWindow()

    # ---- UI 辅助 --------------------------------------------------------
    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _load_server_fields(self, server: str) -> None:
        server = normalize_server(server)
        if not server:
            return
        self.server_edit.setText(server)
        self._on_server_edited(probe=False)

    def _split_address(self, text: str) -> tuple:
        try:
            url = build_server_url(text)
        except ValueError:
            return text.strip(), ""
        parts = urlsplit(url)
        host = parts.hostname or ""
        address = text.strip()
        if host:
            address = f"{parts.scheme}://{host}"
        return address, (str(parts.port) if parts.port else "")

    def _on_server_edited(self, probe: bool = True) -> None:
        """地址里如果写了端口，拆到端口输入框，保持两个字段一致。"""
        address, port = self._split_address(self.server_edit.text())
        self.server_edit.setText(address)
        if port:
            self.port_edit.setText(port)
        if probe:
            self._probe_server()

    def _server_url(self) -> str:
        try:
            return build_server_url(self.server_edit.text(), self.port_edit.text())
        except ValueError as exc:
            self._show_error(str(exc))
            return ""

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.login_button.setEnabled(not busy)
        self.login_button.setText("正在登录…" if busy else "登  录")
        self.server_edit.setEnabled(not busy)
        self.port_edit.setEnabled(not busy)
        self.user_edit.setEnabled(not busy)
        self.password_edit.setEnabled(not busy)
        self.status_label.setText(message)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    # ---- 行为 -----------------------------------------------------------
    def _probe_server(self) -> None:
        server = self._server_url()
        if not server:
            return
        self.server_hint.setText("正在检测服务器…")

        def done(info: dict) -> None:
            name = info.get("ServerName") or "Emby"
            version = info.get("Version") or ""
            self.server_hint.setText(f"{name} · Emby {version}")

        def failed(message: str) -> None:
            self.server_hint.setText("无法连接该服务器")

        run_async(self._public_info, server, on_done=done, on_error=failed)

    def _public_info(self, server: str) -> dict:
        import requests

        proxies = self.proxy_manager.proxies_for(server) if self.proxy_manager else {}
        try:
            resp = requests.get(
                server + "/System/Info/Public",
                timeout=(5, 8),
                proxies=proxies or None,
                trust_env=False,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise EmbyError(f"无法连接服务器：{server}（{exc.__class__.__name__}）") from exc
        return resp.json()

    def _do_login(self) -> None:
        if self._busy:
            return
        try:
            server = build_server_url(self.server_edit.text(), self.port_edit.text())
        except ValueError as exc:
            self._show_error(str(exc))
            return
        username = self.user_edit.text().strip()
        password = self.password_edit.text()
        if not server:
            self._show_error("请填写服务器地址")
            return
        if not username:
            self._show_error("请填写用户名")
            return

        self._show_error("")
        self._set_busy(True, "正在验证账号…")
        if self.proxy_manager is not None:
            self.proxy_manager.force_refresh()
        client = EmbyClient(server, self.config.device_id, proxy_manager=self.proxy_manager)
        self._pending_client = client
        run_async(
            client.login,
            username,
            password,
            on_done=lambda user: self._on_success(client, server, user),
            on_error=self._on_failure,
        )

    def _on_success(self, client: EmbyClient, server: str, user: dict) -> None:
        remember = self.remember_box.isChecked()
        self.config.save_session(server, client.token if remember else "", user, remember)
        self.client = client
        get_logger("login").info("登录成功：%s @ %s", user.get("Name", "—"), server)
        self._set_busy(False, "登录成功")
        self.accept()

    def _on_failure(self, message: str) -> None:
        get_logger("login").warning("登录失败：%s", message)
        self._set_busy(False, "")
        if "允许的客户端" in message:
            message = "服务器拒绝了该客户端名称，请检查客户端白名单设置。"
        self._show_error(message or "登录失败")
