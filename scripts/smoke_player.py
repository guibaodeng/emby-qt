"""播放链路冒烟测试：直连播放 + 进度上报。

用法：
    EMBY_USER=xxx EMBY_PASS=xxx QT_QPA_PLATFORM=xcb PYTHONPATH=. \
        .venv/bin/python scripts/smoke_player.py [item_id]
"""

import sys

from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from embyqt.config import Config
from embyqt.context import AppContext
from embyqt.streamproxy import StreamProxy
from embyqt.ui.playerwindow import PlayerWindow
from embyqt.ui import theme
from _auth import make_client


def wait(app, ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    item_id = sys.argv[1] if len(sys.argv) > 1 else "1127548"
    app = QApplication(sys.argv)
    theme.apply_system(app)

    config = Config()
    config._s.setValue("device/id", "smoke-device-001")
    client = make_client("smoke-device-001")
    proxy = StreamProxy(client)
    proxy.start()
    ctx = AppContext(config, client, proxy)

    item = client.get_item(item_id)
    print("item:", item.get("Name"), item.get("Type"))

    window = PlayerWindow(ctx, item, 0)
    window.resize(1280, 760)
    window.move(60, 60)
    window.show()
    window.raise_()
    window.activateWindow()

    wait(app, 6000)
    for _ in range(10):
        if window._engine is not None:
            break
        wait(app, 2000)
    print("engine ready:", window._engine is not None, "status:", window.status_label.text())
    for _ in range(4):
        wait(app, 2000)
        if window._engine is not None:
            print(
                "time:", window._engine.time_ms(),
                "length:", window._duration_ms,
                "playing:", window._engine.is_playing(),
            )

    if window._engine is not None:
        wait(app, 2500)
        print("frame snapshot rc:", window._engine.snapshot("docs/_player_frame.png"))
        print("audio tracks:", window._engine.audio_tracks())
        print("subtitle tracks:", window._engine.subtitle_tracks())
        window.seek_relative(30_000)
        wait(app, 2500)
        print("after seek:", window._engine.time_ms())

    screen = app.primaryScreen()
    position = window.mapToGlobal(QPoint(0, 0))
    pixmap = screen.grabWindow(0, position.x(), position.y(), window.width(), window.height())
    if pixmap.isNull():
        pixmap = window.grab()
    pixmap.save("docs/screenshot-player.png")
    print("saved docs/screenshot-player.png", pixmap.width(), pixmap.height())

    window.close()
    wait(app, 1200)
    proxy.stop()
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
