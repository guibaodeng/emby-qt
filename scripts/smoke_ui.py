"""无交互 UI 冒烟测试：登录态直连服务器，逐页截图。

用法：
    EMBY_USER=xxx EMBY_PASS=xxx PYTHONPATH=. \
        .venv/bin/python scripts/smoke_ui.py
"""

import json
import sys

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from embyqt.config import Config
from embyqt.context import AppContext
from embyqt.streamproxy import StreamProxy
from embyqt.ui.mainwindow import MainWindow
from embyqt.ui import theme
from _auth import make_client


def wait(app, ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def shot(app, widget, path):
    """优先截取屏幕上真实显示的窗口（不强制全量渲染，保持懒加载语义）。"""
    screen = app.primaryScreen()
    pixmap = screen.grabWindow(widget.winId())
    if pixmap.isNull():
        pixmap = widget.grab()
    pixmap.save(path)
    print("saved", path, pixmap.width(), "x", pixmap.height())


def main() -> int:
    app = QApplication(sys.argv)
    theme.apply_system(app)

    config = Config()
    config._s.setValue("device/id", "smoke-device-001")
    client = make_client("smoke-device-001")
    proxy = StreamProxy(client)
    proxy.start()
    ctx = AppContext(config, client, proxy)

    win = MainWindow(ctx)
    win.resize(1400, 880)
    win.move(40, 40)
    win.show()
    win.raise_()
    win.activateWindow()

    wait(app, 14000)
    hero = win.home_page.hero._item
    print("home rows:", len(win.home_page._rows), "hero:", hero.get("Name") if hero else None)
    shot(app, win, "docs/screenshot-home.png")

    item = None
    for row in win.home_page._rows.values():
        if row.items():
            item = row.items()[0]
            break
    if item:
        print("detail item:", item.get("Name"))
        win._open_detail(item)
        wait(app, 14000)
        wait(app, 4000)
        shot(app, win, "docs/screenshot-detail.png")

    win._on_navigate("search", None)
    wait(app, 400)
    search_page = win._pages["search"]
    search_page.input.setText("流浪")
    wait(app, 7000)
    print("search:", search_page.status.text())
    shot(app, win, "docs/screenshot-search.png")

    movies = [v for v in win._views if v.get("CollectionType") == "movies"]
    if movies:
        key = "lib:" + movies[0]["Id"]
        win._on_navigate(key, None)
        wait(app, 10000)
        page = win._pages[key]
        print("library cards:", len(page._cards), "total:", page._total)
        shot(app, win, "docs/screenshot-library.png")

    win.close()
    proxy.stop()
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
