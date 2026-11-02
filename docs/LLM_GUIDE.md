# LLM / AI 协作指南

> 给大模型的最短上下文。目标：在不破坏现有约束的前提下，快速定位并修改代码。
> 详细原理见 `PROJECT.md`，逐模块见 `MODULES.md`，排障见 `MAINTENANCE.md`。

## 1. 项目一句话

Emby 桌面客户端（PySide6 + libmpv，libVLC 回退），服务器只允许 DirectPlay 且按客户端名白名单，
所有请求必须带 `X-Emby-Authorization`；UI 为无边框 16px 圆角，播放器全局唯一。

## 2. 不可破坏的不变式

1. **认证头**：所有 Emby 请求走 `EmbyClient._request`，带
   `X-Emby-Authorization`（`CLIENT_NAME="Emby for Android"`）。
   不要改成 `?api_key=` 直连；播放内核必须经 `StreamProxy`。
2. **只 DirectPlay**：不要加转码/Remux/下载请求；`device_profile()` 的
   `TranscodingProfiles` 必须保持空。
3. **代理统一**：所有出站请求用 `ProxyManager`（`proxies_for(url)`），
   不要单独 `requests(proxies=...)` 或固定 `QNetworkProxy`；2 秒 TTL；
   `EMBYQT_PROXY=none` 可强制直连。
4. **不阻塞 UI**：网络/耗时操作只用 `run_async`；UI 线程不做 sleep/requests。
5. **建窗前不联网**：`main._restore_client` 只读配置；session 校验在主窗口后台。
6. **单播放器**：`MainWindow._player` 唯一；再次点播走 `PlayerWindow.play_item()`。
7. **Linux 视频**：X11 用 `set_xwindow`，Wayland 用 vmem；禁止 `set_hwnd`（Linux）。
8. **主题**：颜色用 `theme` 调色板/QSS 的 `objectName`；自绘组件读模块级颜色常量；
   不要硬编码新的深色/浅色；播放器控制栏、图标、进度条也已跟随主题。
9. **圆角**：统一 16px，改一处要同步 `theme.py`、`playerwindow.py`、文档、截图。
10. **日志**：`get_logger(...)`；默认开启/DEBUG；不得记录密码、token、Authorization。
11. **单实例布局时序**：播放器 `resizeEvent` 先 `_outer.activate()` 再 `_layout_media()`，
    并 `QTimer.singleShot(0, ...)` 补一次。
12. **不引入启动阻塞**：不要在主线程同步探测服务器/媒体库。

## 3. 架构速览

```text
main.py
 ├ Config + logging + QApplication + theme
 ├ ProxyManager（所有请求的代理来源）
 ├ LoginDialog（无 token 时）
 ├ StreamProxy（本地 HTTP，给 VLC 注入认证头）
 ├ AppContext（client/proxy/images/config）
 └ MainWindow
    ├ Sidebar + QStackedWidget（Home/Library/Search/Settings/Detail）
    └ PlayerWindow（唯一）
       ├ VlcEngine + PlaybackReporter
       └ VideoSurface / ControlBar / ProgressSlider
```

## 4. 文件地图（任务 → 文件）

| 任务 | 主要文件 |
| --- | --- |
| 启动/登录循环/主题/日志初始化 | `embyqt/main.py` |
| 配置项 | `embyqt/config.py`、`embyqt/ui/settings.py` |
| 代理探测 | `embyqt/net.py` |
| Emby 接口 | `embyqt/api.py` |
| 播放流本地代理/网速统计 | `embyqt/streamproxy.py` |
| 图片加载/缓存 | `embyqt/imagecache.py` |
| libmpv 封装/渲染 | `embyqt/mpv_player.py` |
| libVLC 回退/上报 | `embyqt/player.py` |
| 异步任务 | `embyqt/async_task.py` |
| 依赖容器 | `embyqt/context.py` |
| 主题/QSS/颜色 | `embyqt/ui/theme.py` |
| 图标 | `embyqt/ui/icons.py`、`embyqt/assets/icons/` |
| 标题栏/缩放 | `embyqt/ui/titlebar.py`、`embyqt/ui/frameless.py` |
| 主窗口/页面路由/播放器生命周期 | `embyqt/ui/mainwindow.py` |
| 首页 | `embyqt/ui/home.py` |
| 详情/剧集/版本 | `embyqt/ui/detail.py` |
| 媒体库 | `embyqt/ui/library.py` |
| 搜索 | `embyqt/ui/search.py` |
| 设置 | `embyqt/ui/settings.py` |
| 登录框 | `embyqt/ui/login.py` |
| 播放器窗口 | `embyqt/ui/playerwindow.py` |
| 通用组件/海报行/滚轮 | `embyqt/ui/widgets.py` |

## 5. 当前常量（改之前先确认）

| 项 | 值 |
| --- | --- |
| 窗口圆角 | 16px（`theme.py` + `playerwindow.py`） |
| 标题栏高度 | 42px |
| 播放器控制栏 | 96px；图标 24px；按钮 36×36（播放 40）；时间标签 60px 居中；音量悬停浮层 |
| 自动隐藏 | 窗口模式 10s；全屏 2.6s；仅播放中 |
| 代理 TTL | 2.0s |
| 首页继续观看 | 12 |
| 首页每库最新 | 24 |
| 媒体库分页 | 60 |
| 剧集分页 | 30 |
| 搜索上限 | 80 |
| 主窗口初始 | 1400×900，最小 1100×720 |
| 播放器初始 | 1280×760，最小 900×560 |
| 日志默认 | 开启，DEBUG，2MB×3 |
| 主题默认 | system |

## 6. 常见任务配方

### 6.1 改/加一个接口

- `api.py` 的 `EmbyClient` 加方法，走 `_request`；
- 新字段加入 `GRID_FIELDS/DETAIL_FIELDS/EPISODE_FIELDS` 或调用处；
- 解析用 `.get()`；
- 更新 `docs/EMBY_API.md`（如果新增接口）。

### 6.2 加一个设置

- `config.py` property（默认值 + 校验）；
- `settings.py` 控件先 set 再 connect；
- 回调里立即应用；
- 更新 `PROJECT.md` 配置表。

### 6.3 改播放器控制栏

- 按钮：`ControlBar._icon_button`；
- 图标：`icons._SVG_FILES` + `assets/icons/*.svg`；
- 尺寸常量在 `_icon_button`；
- 自动隐藏：`PlayerWindow._hide_timer/_show_controls/_maybe_hide_controls`；
- 播放/暂停/音量/全屏图标更新：`update_*_icon`。

### 6.4 改窗口圆角

全局搜 16：

```bash
grep -R "16px\|set_corner_radius\|_corner_radius\|radius = 16" embyqt
```

同步 `theme.py`、`playerwindow.py`、README、PROJECT、截图。

### 6.5 改代理

- 探测：`net.detect_proxy`；
- 缓存：`ProxyManager`；
- 请求：`EmbyClient._request`、`imagecache._DynamicProxyFactory`、`StreamProxy`；
- 不要绕过 `ProxyManager`。

### 6.6 改播放流程

- 入口：`MainWindow._play_item`；
- 信息：`PlayerWindow._on_playback_info`；
- 流：`_start_stream`；
- 回退：`_retry_with_proxy`；
- 单实例：`play_item`；
- 结束：`_on_ended/_play_next`。

### 6.7 加日志

```python
from embyqt.logging_setup import get_logger
log = get_logger("api")
log.info("...")
```

不打印敏感信息；高频用 DEBUG。

## 7. 命令

```bash
./run.sh
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q embyqt scripts tests
```

调试：

```bash
EMBYQT_PROXY=none ./run.sh            # 强制直连
EMBYQT_PROXY=http://127.0.0.1:7897 ./run.sh
EMBYQT_THEME=light ./run.sh
EMBYQT_FORCE_X11=1 ./run.sh           # 仅需要原生 X11 视频时
EMBYQT_VLC_ARGS="--verbose=2" ./run.sh
EMBYQT_DEBUG_IMAGES=1 ./run.sh
```

## 8. 修改后的验证清单

- [ ] `unittest` 全绿（当前 60 个）；
- [ ] `compileall` 通过；
- [ ] 启动有日志、窗口可见；
- [ ] 首页/详情/剧集/搜索至少各点一次；
- [ ] 点播 A→B，仍是同一个播放器；
- [ ] 暂停遮罩、自动隐藏、最大/全屏/还原；
- [ ] 深/浅/系统主题；
- [ ] 日志开关/级别；
- [ ] 没有 403/代理相关回归；
- [ ] 文档同步。

## 9. 常见错误 → 快速修复

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| 403 请使用群公告中允许的客户端 | 缺认证头/客户端名被改/api_key-only | 走 `_request`；恢复 `CLIENT_NAME`；播放走 StreamProxy |
| 启动后一直没窗口 | 强制 xcb / 建窗前网络阻塞 | 不设 `QT_QPA_PLATFORM=xcb`；恢复异步 |
| 有声音没画面 | Linux 用了 `set_hwnd` | `attach()` 用 `set_xwindow` |
| 图片不跟随代理 | 固定了 QNetworkProxy | 用 `QNetworkProxyFactory` 动态 |
| 重复点播开多窗 | 未复用 `_player` | `play_item` 单实例 |
| 控制栏暂停时消失 | 自动隐藏未判断播放中 | `_maybe_hide_controls` 检查 `is_playing()` |
| 圆角不齐 | 只改了一处 | 同步 theme/player/controlbar |
| 主题改完仍旧色 | 自绘组件没 update/硬编码 | 读 palette 常量并重绘 |
| 日志太大 | 默认 DEBUG 且高频 | 改 INFO 或把高频日志降 DEBUG |
| 设置一打开就触发保存 | 先 connect 后 set | 先 set 后 connect |

## 10. 风格与提交

- UI 文案中文，标识符英文；
- 使用类型注解、dataclass、Qt Signal；
- 不要为小改动引入新依赖；
- 新增文件同步 `docs/MODULES.md`；
- 不提交账号/密码/token、`.venv`、`.cache`、`.config`、`.probe`、`docs/_*.png`。

## 11. 如果你不确定

- 先读目标文件及其调用方，不要凭记忆改接口；
- 不确定服务器行为时，用 `scripts/check_server.py` 探测；
- 不确定 UI 行为时，用真实媒体/真实窗口冒烟；
- 改动涉及播放、代理、认证、启动流程时，优先保守方案并写日志。
