"""只打开播放器窗口，不启动主界面。

用法：
    .venv/bin/python scripts/player_only.py <item_id> [start_seconds]

需要先在 WhalePlayer 中登录过一次，脚本会复用已保存的 Token。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from embyqt.api import EmbyClient  # noqa: E402
from embyqt.config import Config  # noqa: E402
from embyqt.context import AppContext  # noqa: E402
from embyqt.streamproxy import StreamProxy  # noqa: E402
from embyqt.ui import theme  # noqa: E402
from embyqt.ui.branding import app_icon  # noqa: E402
from embyqt.ui.playerwindow import PlayerWindow  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python scripts/player_only.py <item_id> [start_seconds]")
        return 2

    item_id = sys.argv[1]
    try:
        start_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    except ValueError:
        print("start_seconds 必须是数字")
        return 2

    config = Config()
    if not (config.token and config.user_id):
        print("没有已保存的登录态，请先启动 WhalePlayer 登录一次。")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("WhalePlayer")
    app.setApplicationDisplayName("WhalePlayer Player")
    app.setWindowIcon(app_icon())
    theme.apply_preference(app, config.theme)

    client = EmbyClient(
        config.server,
        config.device_id,
        token=config.token,
        user={"Id": config.user_id, "Name": config.user_name},
    )
    proxy = StreamProxy(client)
    proxy.start()
    ctx = AppContext(config, client, proxy)

    try:
        item = client.get_item(item_id)
    except Exception as exc:  # noqa: BLE001
        print(f"获取媒体失败：{exc}")
        proxy.stop()
        return 1

    player = PlayerWindow(ctx, item, int(start_seconds * 10_000_000))
    player.closed.connect(app.quit)
    player.show()
    player.raise_()
    player.activateWindow()
    app.exec()
    proxy.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
