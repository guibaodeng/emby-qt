"""本地配置与登录态持久化（QSettings）。"""

from __future__ import annotations

import uuid

from PySide6.QtCore import QSettings

from . import APP_NAME, ORG_NAME

DEFAULT_SERVER = "https://emby.medi4.org"


class Config:
    def __init__(self) -> None:
        self._s = QSettings(ORG_NAME, APP_NAME)

    # ---- 基础字段 -------------------------------------------------------
    @property
    def server(self) -> str:
        return self._s.value("server", DEFAULT_SERVER, type=str)

    @server.setter
    def server(self, value: str) -> None:
        self._s.setValue("server", value)

    @property
    def token(self) -> str:
        return self._s.value("auth/token", "", type=str)

    @token.setter
    def token(self, value: str) -> None:
        self._s.setValue("auth/token", value)

    @property
    def user_id(self) -> str:
        return self._s.value("auth/user_id", "", type=str)

    @user_id.setter
    def user_id(self, value: str) -> None:
        self._s.setValue("auth/user_id", value)

    @property
    def user_name(self) -> str:
        return self._s.value("auth/user_name", "", type=str)

    @user_name.setter
    def user_name(self, value: str) -> None:
        self._s.setValue("auth/user_name", value)

    @property
    def remember(self) -> bool:
        return self._s.value("auth/remember", True, type=bool)

    @remember.setter
    def remember(self, value: bool) -> None:
        self._s.setValue("auth/remember", value)

    @property
    def device_id(self) -> str:
        value = self._s.value("device/id", "", type=str)
        if not value:
            value = uuid.uuid4().hex
            self._s.setValue("device/id", value)
        return value

    @property
    def volume(self) -> int:
        return self._s.value("player/volume", 80, type=int)

    @volume.setter
    def volume(self, value: int) -> None:
        self._s.setValue("player/volume", int(value))

    @property
    def theme(self) -> str:
        value = self._s.value("ui/theme", "system", type=str)
        return value if value in ("dark", "light", "system") else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        self._s.setValue("ui/theme", value if value in ("dark", "light", "system") else "system")

    @property
    def wheel_mode(self) -> str:
        value = self._s.value("ui/wheel_mode", "page", type=str)
        return value if value in ("page", "row") else "page"

    @wheel_mode.setter
    def wheel_mode(self, value: str) -> None:
        self._s.setValue("ui/wheel_mode", value if value in ("page", "row") else "page")

    @property
    def logging_enabled(self) -> bool:
        return self._s.value("logging/enabled", True, type=bool)

    @logging_enabled.setter
    def logging_enabled(self, value: bool) -> None:
        self._s.setValue("logging/enabled", bool(value))

    @property
    def logging_level(self) -> str:
        value = self._s.value("logging/level", "DEBUG", type=str).upper()
        return value if value in ("INFO", "DEBUG") else "DEBUG"

    @logging_level.setter
    def logging_level(self, value: str) -> None:
        value = str(value).upper()
        self._s.setValue("logging/level", value if value in ("INFO", "DEBUG") else "DEBUG")

    @property
    def last_user_id(self) -> str:
        return self._s.value("auth/last_user", "", type=str)

    def save_session(self, server: str, token: str, user: dict, remember: bool) -> None:
        self.server = server
        self.token = token
        self.user_id = user.get("Id", "")
        self.user_name = user.get("Name", "")
        self.remember = remember
        self._s.setValue("auth/last_user", user.get("Name", ""))
        self._s.sync()

    def clear_session(self) -> None:
        self.token = ""
        self.user_id = ""
        self.user_name = ""
        self._s.sync()

    def clear(self) -> None:
        self._s.clear()
        self._s.sync()
