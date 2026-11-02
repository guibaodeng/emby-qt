# EmbyQt 项目总览

## 1. 项目定位

EmbyQt 是一个桌面 Emby 客户端，目标是把 Emby 的媒体库、详情、剧集、搜索和播放体验
做成一个原生桌面应用，而不是浏览器页面。核心特征：

- **媒体中心界面**：侧边栏媒体库、Hero 推荐、继续观看、最新海报墙、详情页、剧集分页；
- **内嵌播放器**：libVLC 直接解码原文件，不依赖浏览器；
- **无边框窗口**：自绘标题栏、16px 圆角、窗口缩放热区、最大化/全屏；
- **跨平台网络**：自动跟随系统代理，且每个请求前复查；
- **可维护**：核心层与 UI 层分离，配置、日志、代理、播放都有独立模块。

### 1.1 功能模块一览

| 功能模块 | 用户可见能力 | 主要代码 |
| --- | --- | --- |
| 登录 / 会话 | 服务器地址 + 端口、记住登录、Token 恢复、过期重登 | `ui/login.py`、`main.py`、`config.py` |
| 首页 | Hero 推荐、继续观看、每库最新、重试 | `ui/home.py` |
| 媒体库 | 全部影片/类型/年份/排序、无限滚动分页、右键菜单 | `ui/library.py` |
| 详情 / 剧集 | 背景/海报/简介/演职人员、版本选择、收藏/已看、剧集分页、相似推荐 | `ui/detail.py` |
| 搜索 | 防抖搜索、类型筛选、空状态 | `ui/search.py` |
| 播放器 | 单实例、暂停遮罩、缓冲进度、音轨/字幕、自动连播、全屏/最大化、控制栏自动隐藏 | `ui/playerwindow.py`、`player.py` |
| 设置 | 主题三档、日志开关/级别、代理显示、清缓存、重登/退出 | `ui/settings.py` |
| 网络 | 系统代理探测/每请求复查、本机流代理、图片异步加载/缓存 | `net.py`、`streamproxy.py`、`imagecache.py` |
| 窗口系统 | 无边框、16px 圆角、自绘标题栏、拖动/缩放、最大化 | `ui/titlebar.py`、`ui/frameless.py`、`ui/theme.py` |
| 日志 | 终端 + 轮转文件、运行时开关、INFO/DEBUG | `logging_setup.py` |

## 2. 目标服务器与硬约束

这些约束决定了大量设计，改动前必须理解：

### 2.1 客户端白名单（Cloudflare）

服务器在 Cloudflare 层按**客户端名称**做白名单校验。只带 `?api_key=` 的请求会被 403：

```text
403 请使用群公告中允许的客户端进行访问
```

因此所有请求必须带 `X-Emby-Authorization` 头，客户端名固定为：

```python
CLIENT_NAME = "Emby for Android"   # embyqt/__init__.py
```

格式（`EmbyClient.authorization_header`）：

```text
MediaBrowser Client="Emby for Android", Device="EmbyQt Desktop",
DeviceId="<device-id>", Version="1.1.0", Token="<token>"
```

libVLC 无法自定义该头，所以播放走 **本机 StreamProxy**：VLC 只连 `127.0.0.1`，
由 StreamProxy 注入认证头后再转发到服务器。

### 2.2 仅 DirectPlay

目标账号/服务器策略：

- `EnableVideoPlaybackTranscoding = false`
- `EnableAudioPlaybackTranscoding = false`
- `EnablePlaybackRemuxing = false`
- `EnableContentDownloading = false`

客户端因此**不请求转码**：

- `device_profile()` 里 `TranscodingProfiles = []`；
- 只声明 DirectPlay 容器/编码；
- 播放地址使用 `static=true` 的原始文件流；
- 编码不受 libVLC 支持时无法播放，这是预期行为，不做降级。

### 2.3 媒体库规模

服务器媒体库很大（数万部电影、数千部剧集），因此：

- 首页每行最多取 24 个最新条目；
- 库页面分页加载（每页 60）；
- 详情页剧集每页 30，并有上下分页器；
- 图片按需加载 + 磁盘缓存。

> 文档不记录账号、密码或 token。

## 3. 技术栈与运行环境

| 层 | 技术 |
| --- | --- |
| 语言 | Python 3.14（`.venv`），类型注解 + `from __future__ import annotations` |
| UI | PySide6 6.12（Qt 6），仅 Essentials；QtSvg 用于图标 |
| 播放 | python-vlc + 系统 libVLC 3 |
| HTTP | requests（API / 图片后端 / StreamProxy 上游） |
| 图标 | Google Material Symbols Rounded（Apache 2.0），`embyqt/assets/icons/` |

依赖见 `requirements.txt`：

```text
PySide6-Essentials>=6.6
python-vlc>=3.0.20
requests>=2.31
```

系统还需要可用的 libVLC；Linux 上若缺少 `libxcb-cursor0`，仓库 `vendor/lib/` 提供了一份，
`run.sh` 会把它加入 `LD_LIBRARY_PATH`。

### 3.1 平台差异

| 平台 | 状态 | 说明 |
| --- | --- | --- |
| Linux Wayland | 主目标，已验证 | 窗口可见；视频用 vmem 内存渲染，再画到 QWidget |
| Linux X11 | 支持，可切 | `EMBYQT_FORCE_X11=1 ./run.sh`；视频用 `set_xwindow` 原生嵌入 |
| Windows | 代码路径预留 | `set_hwnd` 嵌入；代理依赖 `urllib.getproxies()` 读注册表；待实机验证 |
| macOS | 代码路径预留 | `set_hwnd`；代理读 SystemConfiguration；待实机验证 |

> 不要默认强制 `QT_QPA_PLATFORM=xcb`：某些机器上 `DISPLAY=:0` 是一个不显示窗口的 X 服务，
> 强制 xcb 会导致“进程在跑但看不到界面”。仅在显式 `EMBYQT_FORCE_X11=1` 时切换。

## 4. 目录结构

```text
emby-qt/
├── run.sh                     # 启动脚本（venv、PYTHONPATH、vendor lib）
├── requirements.txt
├── README.md                  # 用户向说明
├── docs/                      # 本维护文档 + 截图
├── embyqt/
│   ├── __init__.py            # 版本、客户端名、设备名
│   ├── __main__.py            # python -m embyqt 入口
│   ├── main.py                # 启动、登录循环、主题/日志/代理初始化
│   ├── config.py              # QSettings 配置
│   ├── logging_setup.py       # 日志配置（运行时开关/级别）
│   ├── net.py                 # 代理探测 + ProxyManager
│   ├── api.py                 # Emby REST 封装
│   ├── streamproxy.py         # 本机 HTTP 流代理（注入认证头/Range/网速统计）
│   ├── imagecache.py          # 异步图片加载 + 内存/磁盘缓存 + Qt 代理工厂
│   ├── player.py              # VlcEngine + PlaybackReporter
│   ├── async_task.py          # QThreadPool 异步任务封装
│   ├── context.py             # AppContext（client/proxy/images/config）
│   ├── ui/
│   │   ├── theme.py           # 两套调色板 + QSS + 主题偏好
│   │   ├── icons.py           # SVG 图标渲染
│   │   ├── branding.py        # 应用图标
│   │   ├── titlebar.py        # 自绘标题栏
│   │   ├── frameless.py       # 无边框缩放热区
│   │   ├── widgets.py         # 通用组件（海报/行/分页/流式布局）
│   │   ├── mainwindow.py      # 主窗口、侧边栏、页面路由、播放器生命周期
│   │   ├── login.py           # 登录框
│   │   ├── home.py            # 首页
│   │   ├── detail.py          # 详情/剧集
│   │   ├── library.py         # 媒体库
│   │   ├── search.py          # 搜索
│   │   ├── settings.py        # 设置
│   │   └── playerwindow.py    # 播放器窗口
│   └── assets/icons/          # Material Symbols SVG + LICENSE/NOTICE
├── scripts/                   # 冒烟/探测脚本（需要测试账号环境变量）
├── tests/                     # 单元测试
└── vendor/lib/                # 可选的 xcb-cursor 动态库
```

## 5. 启动与会话流程

```text
run.sh
  └─ python -m embyqt
       └─ main.main()
            ├─ _configure_qt_platform()      # 仅显式 EMBYQT_FORCE_X11 时切 xcb
            ├─ _silence_qt_noise()           # 关 qt.qpa.wayland.textinput
            ├─ Config() + logging_setup.configure()
            ├─ QApplication + theme.apply_preference(config.theme)
            ├─ ProxyManager()                # 启动时探测一次，之后按 TTL 复查
            ├─ _restore_client()             # 用已保存 token，不在这里发网络请求
            │    ├─ 有 token → EmbyClient（主窗口后台校验）
            │    └─ 无 token → LoginDialog.exec()
            ├─ StreamProxy.start()           # 127.0.0.1 随机端口
            ├─ AppContext(config, client, proxy)
            ├─ MainWindow(ctx).show()
            ├─ app.exec()
            └─ 退出 / 登录过期 / 退出登录 → 必要时循环回登录
```

关键点：

- **建窗之前不阻塞网络**：`_restore_client` 不校验 token；主窗口先显示，后台 `get_user` 校验。
  这样服务器慢时不会出现“执行 run.sh 后一直没反应”。
- 登录过期由 `MainWindow.session_expired` 通知 `main`，清 token 后回到登录框。
- 退出登录同样清 session；正常关窗直接退出。
- 主题和日志在创建窗口前初始化，登录框也使用同一主题。

## 6. 网络与代理

### 6.1 探测优先级

`net.detect_proxy()`：

1. `EMBYQT_PROXY` 覆盖（`none/off/direct` 强制直连）；
2. `urllib.request.getproxies()`：Linux 环境变量、Windows 注册表、macOS SystemConfiguration；
3. Linux 桌面补充：GNOME gsettings（manual / PAC）、KDE `kioslaverc`；
4. 都没有 → 直连。

### 6.2 每个请求前复查

`ProxyManager` 缓存 2 秒（`ttl=2.0`），每次网络请求前调用：

- `EmbyClient._request` → `proxy_manager.proxies_for(url)`；
- `ImageStore` 的 `QNetworkProxyFactory.queryProxy()` → 每个图片请求动态判断；
- `StreamProxy` 的每个上游请求 → `client.proxy_manager.proxies_for(upstream)`；
- 播放开始、登录、设置页显示 → `force_refresh()`。

代理变化会写日志：`系统代理已变更：...`。

### 6.3 规则

- **有代理全走，无代理全不走**；不允许 API 走代理、图片直连这种割裂；
- `localhost/127.0.0.0/8/::1` 等按 `bypass` 跳过；
- `requests.Session.trust_env = False`，避免 requests 再读一份环境代理；
- 播放媒体有系统代理时固定走本机 StreamProxy（不直连），避免绕过代理。

### 6.4 已知边界

- PAC 复杂规则目前是“取第一条 PROXY/HTTPS”兜底，未做按 URL 分流；
- Windows/macOS 的 PAC 自动配置依赖 `urllib.getproxies()` 能取到的系统项；
- 代理没启动时连接会失败，错误提示会区分代理/超时/TLS/连接错误。

## 7. 播放链路

```text
用户点播（首页/详情/剧集）
  └─ MainWindow._play_item()
       ├─ Series → 打开详情页
       ├─ 从详情页取 playlist/index 与 media_source_id
       ├─ 已有 player？ → player.play_item(...)   # 单实例，窗口内切换
       └─ 否则创建 PlayerWindow
            └─ _load() → client.playback_info()
                 └─ _on_playback_info()
                      ├─ 选择 MediaSource（版本）
                      ├─ 创建/复用 VlcEngine
                      ├─ Wayland → attach_vmem() + frame_ready → VideoSurface
                      ├─ X11     → attach(winId) + set_xwindow
                      ├─ PlaybackReporter.start()
                      └─ _start_stream()
                           ├─ 有系统代理 → StreamProxy.media_url()
                           └─ 无系统代理 → 直连 static URL（失败可回退本机代理）
                                └─ VlcEngine.play()
```

### 7.1 关键行为

- **全局唯一播放器**：`MainWindow._player` 只保留一个 `PlayerWindow`；
  再次点播调用 `play_item` 切换媒体，不会开新窗口；关闭后清空引用。
- **剧集自动连播**：`playlist` + `index`，结束且接近片尾时 `_play_next()`。
- **接近片尾判定**：`_last_position_ms >= runtime * 0.92`，避免网络中断被误判为播放结束。
- **播放上报**：开始/每 10 秒/暂停拖动/退出，`PlayMethod="DirectPlay"`。
- **位置恢复**：从 `UserData.PlaybackPositionTicks` 换算成毫秒起始。
- **加载遮罩**：起播/切换/重试时，画面中心显示与暂停遮罩同尺寸的转圈，下方显示实时网速（由本机流代理的字节计数计算）；首帧到达后自动消失。
- **控制栏网速**：音量图标右侧显示 speed 图标 + 实时网速（同样来自本机流代理）；直连模式显示“直连”。
- **音量**：鼠标悬停音量图标时，在控制栏上方浮出垂直音量滑条；点击图标仍切换静音。
- **暂停遮罩**：暂停且已播放时，画面中心显示半透明暂停图标。
  进度条支持**点击/拖动任意位置**定位播放；单击视频画面暂停/继续，双击全屏。
- **控制栏**：Material Symbols 图标，背景/文字/图标/进度条跟随深/浅色主题；窗口模式播放中 10 秒无操作隐藏，全屏 2.6 秒；
  鼠标移动/点击/键盘操作恢复。

### 7.2 版本选择

详情页 `MediaSources` 有多个版本时显示下拉框（4K/1080P/720P 等），
`media_source_id` 一路传到 `playback_info` 和 `stream` 地址；只有一个版本时隐藏。

## 8. 窗口与 UI 结构

```text
MainWindow (frameless, translucent)
└─ windowRoot (8px 外边距)
   └─ windowFrame (16px 圆角)
      ├─ TitleBar (42px, 拖动/双击最大化/最小化/最大化/关闭)
      ├─ body
      │  ├─ Sidebar（首页/搜索/收藏/媒体库/设置/用户信息）
      │  └─ QStackedWidget
      │       ├─ HomePage
      │       ├─ LibraryPage × N
      │       ├─ SearchPage
      │       ├─ SettingsPage
      │       └─ DetailPage × N（详情栈，Alt+← 返回）
      └─ windowStatus（26px，圆角底边）
```

- 所有窗口（主窗口、登录框、播放器）**无系统标题栏**；
- 统一 **16px** 圆角；最大化/全屏时外边距与圆角归零；
- 播放器不保留外层透明边距；窗口模式 playerFrame 使用 1px 主题边框，视频组件不设边框；
  全屏/最大化时去掉边框并把 frame 背景设为黑色，避免屏幕边缘出现浅色细线；
  主窗口/登录框仍保留 8px 透明边距用于圆角和缩放热区；
- 播放器 frame 背景使用主题背景色，视频底部圆角用 mask 裁剪（半径比控制栏大 4px），
  避免半透明控制栏圆角外露出黑色视频边；控制栏浅色透明度 0.84、深色 0.78。
- 缩放：`frameless.ResizeHandle` 在四边/四角放透明热区，调用 `startSystemResize`；
- 拖动：`TitleBar` 调用 `startSystemMove`，双击触发最大化；
- 播放器窗口化时视频底部按 16px 裁剪；X11 原生视频子窗口的圆角受平台限制。

### 8.1 页面行为速查

| 页面 | 行为 |
| --- | --- |
| 首页 | Hero 推荐 + 继续观看（12）+ 每个媒体库最新（24），行内自适应填充/横向滚动 |
| 媒体库 | 每页 60，滚动到底加载；类型/年份/排序/升序筛选；合集/演员等类型 |
| 详情 | 背景、海报、版本选择、收藏/已看、演职人员、剧集分页（30/页）、相似推荐 |
| 搜索 | 防抖、类型筛选（全部/电影/剧集/单集/合集）、空状态 |
| 设置 | 服务器/用户/代理/设备/版本、主题三档、日志开关与级别、鼠标滚轮行为、清缓存/重登/退出 |
| 登录 | 服务器地址 + 端口、探测服务器名、记住登录、无边框圆角 |

## 9. 主题、图标、日志

### 9.1 主题

- `theme.DARK` / `theme.LIGHT` 两套调色板；`build_stylesheet()` 生成 QSS；
- 组件通过 `objectName` 取样式；自绘组件读取模块级颜色常量（`BG/TEXT/...`）；
- `theme.apply_preference(app, mode)`：`dark / light / system`；
- `system` 用 `QStyleHints.colorScheme()`，读不到时回退到系统调色板亮度；
- 系统主题变化信号只在该偏好下生效；
- 设置里切换即时应用并持久化到 `ui/theme`。

### 9.2 图标

- `embyqt/assets/icons/*.svg` 来自 Material Symbols Rounded（Apache 2.0）；
- `icons.icon(name, size)` 用 QtSvg 渲染，并把 `fill` 注入成 `#eef2fb`；
- 名称到文件的映射在 `icons._SVG_FILES`；
- 图标颜色跟随主题（浅色主题用深色图标）；QtSvg 不可用时回退到 `_draw` 内置矢量。

### 9.3 日志

- `logging_setup.configure(enabled, level)` 可运行时重配；
- 默认开启、默认 `DEBUG`；
- 终端 + 轮转文件（2MB × 3）；
- 路径：Linux `~/.local/state/embyqt/logs/`，macOS `~/Library/Logs/embyqt/`，
  Windows `%LOCALAPPDATA%\embyqt\logs\`；
- 覆盖登录、代理、API 请求、播放、页面切换、错误；
- **不记录密码/token**；
- `_silence_qt_noise()` 关闭 `qt.qpa.wayland.textinput` 刷屏警告。

## 10. 配置、缓存与敏感信息

### 10.1 QSettings 键

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `server` | `https://emby.medi4.org` | 服务器 URL（含子路径） |
| `auth/token` | 空 | 访问 token（明文） |
| `auth/user_id` / `auth/user_name` | 空 | 当前用户 |
| `auth/remember` | `true` | 是否保存 token |
| `auth/last_user` | 空 | 上次用户名 |
| `device/id` | 随机 UUID | 设备 ID，稳定不变 |
| `player/volume` | `80` | 音量 |
| `ui/theme` | `system` | `system/dark/light` |
| `ui/wheel_mode` | `page` | `page`（页面上下）/`row`（分类左右） |
| `logging/enabled` | `true` | 日志开关 |
| `logging/level` | `DEBUG` | `INFO/DEBUG` |

### 10.2 缓存

- 图片：`QStandardPaths.CacheLocation/images`，磁盘上限 512MB；内存 LRU；
- 图片加载失败会退回占位图，不阻塞 UI；
- 日志：见上。

### 10.3 安全

- token 以明文存在 QSettings；文档/日志/截图不要带 token 或密码；
- 登录框密码不落盘（除非 remember 只保存 token）；
- API 日志只记录 method/path/status/耗时，不记录 header。

## 11. 关键设计决策

| 决策 | 原因 |
| --- | --- |
| 固定 `CLIENT_NAME="Emby for Android"` | 服务器 Cloudflare 白名单只放行特定客户端名 |
| 本机 StreamProxy 注入认证头 | libVLC 不能设置自定义 Emby 头 |
| 不请求转码 | 服务器关闭转码/Remux/下载，请求也会失败 |
| 代理每个请求复查（2s TTL） | 用户可能中途开关系统代理；避免只在启动时判断 |
| 先建窗再校验 session | 避免服务器慢时启动“卡住” |
| Wayland vmem、X11 原生嵌入 | Linux 上 `set_hwnd` 会导致 vout=none（有声音没画面） |
| 单实例播放器 | 避免重复点播开多个窗口，符合桌面播放器习惯 |
| `run_async` + Qt 信号 | 网络/图片/播放上报不阻塞 UI 线程 |
| 无边框 + 自绘标题栏 | 系统标题栏无法跟随主题；圆角统一 |

## 12. 已知限制

- 无转码：编码不支持时不能播放；
- Wayland vmem 4K 高码率比 X11 原生嵌入更吃 CPU；
- X11 原生视频窗口的底部圆角可能仍是直角（VLC 子窗口限制）；
- PAC 复杂规则只做默认代理兜底；
- 登录 token 明文保存；
- 部分无索引的 MKV/HTTP 流不能跳转，会提示“当前视频不支持跳转”；
- 暂未实现：弹幕、下载缓存、直播电视、多用户切换、播放列表管理；
- Windows/macOS 尚未实机验证，跨平台细节以代码路径为准。
