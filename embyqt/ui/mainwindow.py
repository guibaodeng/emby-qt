"""主窗口：侧边栏导航 + 页面堆栈。"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .. import __version__
from ..api import EmbyError
from ..async_task import run_async
from ..context import AppContext
from . import theme
from .branding import app_icon
from .icons import icon
from .detail import DetailPage
from .home import HomePage
from .library import LibraryPage
from .playerwindow import PlayerWindow
from .search import SearchPage
from .settings import SettingsPage
from .frameless import create_resize_handles, position_resize_handles
from .titlebar import TitleBar
from ..logging_setup import get_logger
from .widgets import ElidedLabel, make_button


def _is_auth_error(message: str) -> bool:
    return "认证失败" in message or "401" in message


def _avatar_pixmap(text: str, size: int = 36) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2f6b2d"))
    painter.drawEllipse(0, 0, size, size)
    painter.setPen(QColor("#d9f5d6"))
    font = QFont()
    font.setPointSize(max(9, size // 3))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QRectF(0, 0, size, size),
        Qt.AlignmentFlag.AlignCenter,
        (text or "?")[:1].upper(),
    )
    painter.end()
    return pixmap


class Sidebar(QFrame):
    navigate = Signal(str, object)
    logout_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        self._buttons: Dict[str, "QPushButton"] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._libraries_box: Optional[QVBoxLayout] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(2)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon(38).pixmap(38, 38))
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("WhalePlayer")
        name.setObjectName("brandName")
        brand_text.addWidget(name)
        self.server_label = ElidedLabel("")
        self.server_label.setObjectName("sidebarServer")
        brand_text.addWidget(self.server_label)
        brand.addLayout(brand_text, 1)
        layout.addLayout(brand)
        layout.addSpacing(18)

        for key, label in (
            ("home", "首页"),
            ("search", "搜索"),
            ("favorites", "我的收藏"),
        ):
            button = self._nav_button(key, label)
            layout.addWidget(button)

        self._library_section = QLabel("媒体库")
        self._library_section.setObjectName("sidebarSection")
        layout.addWidget(self._library_section)

        self._libs_widget = QWidget()
        self._libraries_box = QVBoxLayout(self._libs_widget)
        self._libraries_box.setContentsMargins(0, 0, 0, 0)
        self._libraries_box.setSpacing(2)
        self._libraries_box.addStretch(1)

        self._libs_scroll = QScrollArea()
        self._libs_scroll.setWidgetResizable(True)
        self._libs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._libs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._libs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._libs_scroll.setWidget(self._libs_widget)
        layout.addWidget(self._libs_scroll, 1)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFixedHeight(1)
        layout.addSpacing(6)
        layout.addWidget(divider)
        layout.addSpacing(6)

        self.user_button = QPushButton(self)
        self.user_button.setObjectName("userMenuButton")
        self.user_button.setFlat(True)
        self.user_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.user_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.user_button.setFixedHeight(54)
        self.user_button.clicked.connect(self._show_user_menu)
        user_row = QHBoxLayout(self.user_button)
        user_row.setContentsMargins(6, 4, 6, 4)
        user_row.setSpacing(10)
        self.avatar = QLabel()
        self.avatar.setFixedSize(36, 36)
        self.avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        user_row.addWidget(self.avatar)
        user_text = QVBoxLayout()
        user_text.setSpacing(1)
        self.user_name = ElidedLabel("")
        self.user_name.setObjectName("userName")
        self.user_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        user_text.addWidget(self.user_name)
        self.user_role = QLabel("")
        self.user_role.setObjectName("userRole")
        self.user_role.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        user_text.addWidget(self.user_role)
        user_row.addLayout(user_text, 1)
        layout.addWidget(self.user_button)

        version = QLabel(f"v{__version__}")
        version.setObjectName("sidebarVersion")
        layout.addWidget(version)

    def _add_user_menu_action(self, menu: QMenu, icon_name: str, text: str, callback) -> None:
        action = QWidgetAction(menu)
        button = QPushButton(text, menu)
        button.setObjectName("userMenuItem")
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(icon(icon_name, 16, theme.TEXT))
        button.setIconSize(QSize(16, 16))
        button.setFixedHeight(34)
        button.setMinimumWidth(150)
        button.clicked.connect(lambda _checked=False: (menu.close(), callback()))
        action.setDefaultWidget(button)
        menu.addAction(action)

    def _show_user_menu(self) -> None:
        menu = QMenu(self)
        self._add_user_menu_action(
            menu, "settings", "设置", lambda: self.navigate.emit("settings", None)
        )
        menu.addSeparator()
        self._add_user_menu_action(menu, "logout", "退出登录", self.logout_requested.emit)
        pos = self.user_button.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(pos.x(), pos.y() - menu.sizeHint().height()))

    def _nav_button(self, key: str, label: str, parent: Optional[QWidget] = None) -> "QPushButton":
        button = make_button(label, "nav", parent or self)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(34)
        self._group.addButton(button)
        button.clicked.connect(lambda _checked=False, k=key: self.navigate.emit(k, None))
        self._buttons[key] = button
        return button

    def set_user(self, user: dict) -> None:
        name = user.get("Name", "")
        self.user_name.setText(name)
        self.avatar.setPixmap(_avatar_pixmap(name, 36))
        policy = user.get("Policy") or {}
        self.user_role.setText("管理员" if policy.get("IsAdministrator") else "普通用户")

    def set_server(self, server: str) -> None:
        text = server.replace("https://", "").replace("http://", "").rstrip("/")
        self.server_label.setText(text)

    def set_libraries(self, views: List[dict]) -> None:
        if self._libraries_box is None:
            return
        while self._libraries_box.count():
            item = self._libraries_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for key in [k for k in self._buttons if k.startswith("lib:")]:
            button = self._buttons.pop(key)
            if button is not None:
                self._group.removeButton(button)
        for view in views:
            key = f"lib:{view.get('Id')}"
            button = self._nav_button(key, view.get("Name", "媒体库"), self._libs_widget)
            self._libraries_box.addWidget(button)
        self._libraries_box.addStretch(1)
        self._library_section.setVisible(bool(views))

    def check(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def clear_check(self) -> None:
        self._group.setExclusive(False)
        for button in self._group.buttons():
            button.setChecked(False)
        self._group.setExclusive(True)


class MainWindow(QMainWindow):
    logout_requested = Signal()
    session_expired = Signal()

    def __init__(self, ctx: AppContext, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._views: List[dict] = []
        self._pages: Dict[str, QWidget] = {}
        self._detail_pages: List[DetailPage] = []
        self._player: Optional[PlayerWindow] = None
        self._current_key = "home"
        self._settings_back_key = "home"
        self._views_retries = 0
        self._expiring = False

        self.setObjectName("mainWindow")
        self.setWindowTitle("WhalePlayer")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(1100, 720)
        self.resize(1400, 900)

        # 外层留 8px 透明边距，用于放阴影和缩放热区
        self._root = QWidget()
        self._root.setObjectName("windowRoot")
        self.setCentralWidget(self._root)
        self._root_layout = QVBoxLayout(self._root)
        self._root_layout.setContentsMargins(8, 8, 8, 8)
        self._root_layout.setSpacing(0)

        self.frame = QFrame()
        self.frame.setObjectName("windowFrame")
        self.frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._root_layout.addWidget(self.frame)

        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self.title_bar = TitleBar("WhalePlayer", app_icon(), parent=self.frame)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_maximized)
        self.title_bar.close_requested.connect(self.close)
        frame_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self._on_navigate)
        self.sidebar.logout_requested.connect(self._on_logout)
        body_layout.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        body_layout.addWidget(self.stack, 1)
        frame_layout.addWidget(body, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("windowStatus")
        self.status_label.setFixedHeight(26)
        frame_layout.addWidget(self.status_label)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.status_label.setText(""))

        self._handles = create_resize_handles(self)
        self._apply_window_state()

        self.sidebar.set_server(self.ctx.client.server)
        self.sidebar.set_user(self.ctx.client.user)

        self.home_page = self._ensure_page("home")
        self.sidebar.check("home")
        self.stack.setCurrentWidget(self.home_page)

        self._install_shortcuts()
        self._load_views()
        self._check_session()

    # ---- 无边框窗口 -----------------------------------------------------
    def _position_resize_handles(self) -> None:
        if hasattr(self, "_handles"):
            position_resize_handles(self, self._handles)

    def _apply_window_state(self) -> None:
        maximized = self.isMaximized()
        margin = 0 if maximized else 8
        self._root_layout.setContentsMargins(margin, margin, margin, margin)
        for widget in (self.frame, self.title_bar, self.status_label):
            widget.setProperty("maximized", maximized)
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self.title_bar.set_maximized(maximized)
        for handle in self._handles:
            handle.setVisible(not maximized)
        self._position_resize_handles()

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._apply_window_state)
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_resize_handles()

    def _show_status(self, message: str, timeout: int = 8000) -> None:
        self.status_label.setText(message)
        self._status_timer.start(timeout)

    # ---- 页面管理 -------------------------------------------------------
    def _ensure_page(self, key: str) -> QWidget:
        page = self._pages.get(key)
        if page is not None:
            return page

        if key == "home":
            page = HomePage(self.ctx)
            page.open_item.connect(self._open_detail)
            page.play_item.connect(self._play_item)
            page.load()
        elif key == "search":
            page = SearchPage(self.ctx)
            page.open_item.connect(self._open_detail)
            page.play_item.connect(self._play_item)
        elif key == "favorites":
            page = LibraryPage(
                self.ctx,
                {"Id": "", "Name": "我的收藏"},
                filters="IsFavorite",
                include_types="Movie,Series,BoxSet,Video,Episode",
                show_genre=False,
            )
            page.open_item.connect(self._open_detail)
            page.play_item.connect(self._play_item)
        elif key == "settings":
            page = SettingsPage(self.ctx)
            page.logout_requested.connect(self._on_logout)
            page.relogin_requested.connect(self._on_logout)
            page.back_requested.connect(self._close_settings)
        elif key.startswith("lib:"):
            view_id = key.split(":", 1)[1]
            view = next((v for v in self._views if str(v.get("Id")) == view_id), None)
            if view is None:
                return self.home_page
            page = LibraryPage(self.ctx, view)
            page.open_item.connect(self._open_detail)
            page.play_item.connect(self._play_item)
        else:
            page = self.home_page

        self._pages[key] = page
        self.stack.addWidget(page)
        return page

    def _on_navigate(self, key: str, data: object) -> None:
        get_logger("ui").info("切换页面：%s", key)
        if key == "settings" and self._current_key != "settings":
            self._settings_back_key = self._current_key or "home"
        page = self._ensure_page(key)
        self.stack.setCurrentWidget(page)
        self._current_key = key
        if key == "settings":
            self.sidebar.clear_check()
        else:
            self.sidebar.check(key)
        if key == "search" and isinstance(page, SearchPage):
            page.focus_search()

    def _close_settings(self) -> None:
        key = self._settings_back_key or "home"
        if key == "settings":
            key = "home"
        if key not in self._pages and not key.startswith("lib:"):
            key = "home"
        self._on_navigate(key, None)

    def _load_views(self) -> None:
        run_async(
            self.ctx.client.get_views,
            on_done=self._on_views,
            on_error=self._on_views_error,
        )

    def _on_views(self, views: List[dict]) -> None:
        self._views = views
        self._views_retries = 0
        self._expiring = False
        self.sidebar.set_libraries(views)

    def _on_views_error(self, message: str) -> None:
        if _is_auth_error(message):
            self._expire_session()
            return
        self._show_status(f"媒体库加载失败：{message}")
        if self._views_retries < 2:
            self._views_retries += 1
            QTimer.singleShot(1500, self._load_views)

    # ---- 登录态 ---------------------------------------------------------
    def _check_session(self) -> None:
        """后台校验保存的 token，避免启动时阻塞在建窗之前。"""
        run_async(
            self.ctx.client.get_user,
            on_done=self._on_user,
            on_error=self._on_user_error,
        )

    def _on_user(self, user: dict) -> None:
        if not isinstance(user, dict) or not user.get("Id"):
            return
        self.ctx.client.user = user
        self.sidebar.set_user(user)

    def _on_user_error(self, message: str) -> None:
        if _is_auth_error(message):
            self._expire_session()
        else:
            self._show_status(f"登录状态校验失败：{message}")

    def _expire_session(self) -> None:
        if self._expiring:
            return
        get_logger("ui").warning("登录状态已过期")
        self._expiring = True
        self._show_status("登录已过期，请重新登录")
        QTimer.singleShot(1200, self.session_expired.emit)

    # ---- 详情 -----------------------------------------------------------
    def _open_detail(self, item: dict) -> None:
        page = DetailPage(self.ctx, item)
        page.back_requested.connect(self._close_detail)
        page.play_requested.connect(self._play_item)
        page.open_item.connect(self._open_detail)
        page.state_changed.connect(self._refresh_current_page)
        self._detail_pages.append(page)
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.sidebar.clear_check()

    def _close_detail(self) -> None:
        if not self._detail_pages:
            return
        page = self._detail_pages.pop()
        if self.stack.currentWidget() is page:
            previous = self._detail_pages[-1] if self._detail_pages else self._pages.get(self._current_key)
            if previous is not None:
                self.stack.setCurrentWidget(previous)
        self.stack.removeWidget(page)
        page.deleteLater()
        if not self._detail_pages:
            self.sidebar.check(self._current_key)

    def _refresh_current_page(self) -> None:
        widget = self.stack.currentWidget()
        if isinstance(widget, DetailPage):
            widget.refresh()

    # ---- 播放 -----------------------------------------------------------
    def _play_item(self, item: dict, start_ticks: int = 0) -> None:
        if not item:
            return
        get_logger("ui").info("点播：%s（%s）", item.get("Name", "—"), item.get("Id", "—"))
        if item.get("Type") == "Series":
            self._open_detail(item)
            return
        playlist: List[dict] = []
        index = -1
        media_source_id = ""
        for page in reversed(self._detail_pages):
            episodes, episode_index = page.episode_playlist(item)
            if episodes:
                playlist, index = episodes, episode_index
                break
            source_id = page.media_source_id_for(item)
            if source_id:
                media_source_id = source_id
                break

        # 单实例播放器：已有窗口时直接在里面切换视频
        if self._player is not None and not self._player._closing:
            self._player.play_item(
                item,
                start_ticks,
                playlist,
                index,
                media_source_id=media_source_id,
            )
            self._player.show()
            self._player.raise_()
            self._player.activateWindow()
            return
        self._player = None

        player = PlayerWindow(
            self.ctx,
            item,
            start_ticks,
            playlist,
            index,
            media_source_id=media_source_id,
        )
        player.closed.connect(lambda p=player: self._on_player_closed(p))
        self._player = player
        player.show()
        player.raise_()
        player.activateWindow()

    def _on_player_closed(self, player: PlayerWindow) -> None:
        get_logger("ui").debug("播放器窗口已关闭")
        if self._player is player:
            self._player = None
        player.deleteLater()
        self._refresh_current_page()

    # ---- 退出 -----------------------------------------------------------
    def _on_logout(self) -> None:
        self.logout_requested.emit()

    def _install_shortcuts(self) -> None:
        search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        search_shortcut.activated.connect(lambda: self._on_navigate("search", None))
        home_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
        home_shortcut.activated.connect(lambda: self._on_navigate("home", None))
        back_shortcut = QShortcut(QKeySequence("Alt+Left"), self)
        back_shortcut.activated.connect(self._close_detail)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._player is not None:
            self._player.close()
        super().closeEvent(event)
