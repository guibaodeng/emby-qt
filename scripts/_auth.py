"""测试脚本共用的登录辅助。

优先读取 .probe/login.json（本地测试产物），否则用环境变量登录：
    EMBY_SERVER / EMBY_USER / EMBY_PASS
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embyqt.api import EmbyClient  # noqa: E402
from embyqt.net import detect_proxy  # noqa: E402


def make_client(device: str) -> EmbyClient:
    server = os.environ.get("EMBY_SERVER", "https://emby.medi4.org")
    path = os.environ.get("EMBY_LOGIN_JSON", ".probe/login.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        token = data.get("AccessToken") or data.get("token") or ""
        user = data.get("User") or data.get("user") or {}
        if token:
            return EmbyClient(server, device, token=token, user=user, proxy=detect_proxy())

    username = os.environ.get("EMBY_USER", "")
    password = os.environ.get("EMBY_PASS", "")
    if not username or not password:
        raise SystemExit(
            "缺少登录信息：请设置 EMBY_USER / EMBY_PASS，或提供 .probe/login.json"
        )
    client = EmbyClient(server, device, proxy=detect_proxy())
    client.login(username, password)
    return client
