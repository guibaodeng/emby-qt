# EmbyQt 模块手册

本文件按“文件 → 职责 → 关键接口 → 修改注意点”说明代码。开始改代码前先找到对应条目。

## 0. 分层约定

```text
core:  main / config / logging_setup / net / api / streamproxy / imagecache / player / async_task / context
ui:    theme / icons / branding / titlebar / frameless / widgets
       mainwindow / login / home / detail / library / search / settings / playerwindow
```

- **core 不依赖 UI**（`main.py` 除外，它是装配层）；
- UI 通过 `AppContext` 拿到 client / proxy / images / config；
- 网络与播放只在后台线程执行，UI 线程只做绘制和信号回调；
- 所有 Emby 请求都经过 `EmbyClient._request`，不要绕开它直接 requests。

---

## 1. 入口与装配层

### `embyqt/__init__.py`

- 版本号：`__version__ = "1.1.0"`；
- 客户端标识：`CLIENT_NAME = "Emby for Android"`、`CLIENT_VERSION = "1.1.0"`、
  `DEVICE_NAME = "WhalePlayer Desktop"`、`APP_NAME/ORG_NAME`；QSettings 使用旧键名兼容登录态。
- **注意**：`CLIENT_NAME` 是服务器白名单放行的名称，改动会导致所有请求 403；
  `CLIENT_VERSION` 是 Emby 协议里的客户端版本，与 App 版本分开。

### `embyqt/__main__.py`

- `python -m embyqt` 的薄入口，调用 `main.main()`。

### `embyqt/main.py`

- `_configure_qt_platform()`：只有显式 `EMBYQT_FORCE_X11=1` 才切换到 xcb；
- `_silence_qt_noise()`：追加 `QT_LOGGING_RULES=qt.qpa.wayland.textinput=false`；
- `_restore_client()`：用保存的 token 构造客户端，**不发网络请求**；
- `main()`：日志 → QApplication → 主题 → ProxyManager → 登录/主窗口循环。
- **注意**：
  - 不要在 `main` 的建窗前做同步网络请求（慢服务器会导致“启动无反应”）；
  - 登录过期/退出登录通过 `MainWindow` 信号回到这里，清 session 后再循环；
  - 主题由 `config.theme` 决定，`EMBYQT_THEME=dark|light|blue|system` 可临时覆盖。

---

## 2. 核心层

### `embyqt/config.py`

- `Config`：QSettings 封装（`QSettings("EmbyQt", "EmbyQt")`）。
- 关键属性：`server / token / user_id / user_name / remember / device_id / volume /
  theme / logging_enabled / logging_level / last_user_id`。
- 方法：`save_session()`、`clear_session()`、`clear()`。
- **注意**：
  - `device_id` 首次访问随机生成并持久化，不要每次启动变；
  - `theme` 只接受 `system/dark/light`，`logging_level` 只接受 `INFO/DEBUG`；
  - token 明文保存，不要在文档/日志中打印。

### `embyqt/logging_setup.py`

- `configure(enabled=True, level="DEBUG")`：重建 handler；关闭时清空并 `disabled=True`。
- `get_logger(name)`：统一 `embyqt.<name>` 命名。
- `log_file_path()`：按平台返回日志路径。
- 输出：stderr + `RotatingFileHandler`（2MB × 3）。
- **注意**：
  - 默认开启、默认 DEBUG；
  - 不要在日志里写密码、token、Authorization header；
  - 设置页运行中重配会立即生效，不需要重启。

### `embyqt/net.py`

- `ProxyConfig`：url/host/port/scheme/source/bypass；`enabled`、`describe()`、
  `signature()`、`bypass_for()`、`proxies_for()`。
- `detect_proxy()`：`EMBYQT_PROXY` → `urllib.getproxies()` → macOS `scutil`（PAC）→ Linux GNOME/KDE → None。
- `ProxyManager`：TTL 缓存（默认 2s），`current()`/`force_refresh()`/`proxies_for()`/
  `describe()`；内部锁保证并发只探测一次。
- `default_manager()`：进程级默认管理器（`EmbyClient` 未显式传 manager 时使用）。
- **注意**：
  - 所有请求前都应调用 `proxies_for(url)`，不要自己读环境变量；
  - `trust_env=False` 是刻意设置，避免出现两套代理；
  - `EMBYQT_PROXY=none` 可强制直连，排障时很有用；
  - 复杂 PAC 只取第一条 PROXY/HTTPS，未做按 URL 分流。

### `embyqt/api.py`

- `EmbyError(message, status)`：统一异常；`status` 为 HTTP 码或 `None`。
- `normalize_server()` / `build_server_url()`：地址规范化、地址+端口拼接。
- `image_url()`：构造图片地址（tag/maxWidth/quality）。
- `EmbyClient`：
  - 认证：`login()`、`logout()`、`server_info()`、`get_user()`；
  - 媒体库：`get_views()`、`get_latest()`、`get_resume()`、`get_items()`、`get_item()`、
    `get_genres()`、`search()`；
  - 剧集：`get_seasons()`、`get_episodes()`；
  - 用户数据：`set_favorite()`、`set_played()`；
  - 播放：`device_profile()`、`playback_info()`、`report_start/progress/stop()`；
  - 地址：`image()`、`item_image()`、`stream_path()`、`subtitle_path()`；
  - `_request()`：统一注入认证头、代理、重试、错误转换、日志。
- **注意**：
  - 请求必须带 `X-Emby-Authorization`（`authorization_header()`）；
  - 不要新增转码请求（DirectPlay only）；
  - `_request` 对 GET/Authenticate 最多 3 次，其他 1 次；代理错误会 `force_refresh()`；
  - `TICKS = 10_000_000`（1 秒），播放位置全部用 ticks 上报。

### `embyqt/streamproxy.py`

- `StreamProxy`：在 `127.0.0.1:随机端口` 起线程 HTTP 服务，供 libmpv/libVLC 播放/字幕和网速统计。
- `media_url()` / `subtitle_url()`：本机 URL；
- `begin_playback/begin_request/add_progress/set_progress_total/bytes_for/windows_for/begin_seek()`：
  每个 Range 请求保留一个窗口（start/sent），`windows_for()` 返回合并后的缓冲区间；
  `downloaded` 累计字节用于实时网速；
  `begin_seek()` 检查目标是否已缓冲：已缓冲则保留窗口，未缓冲则清空，后续请求从新位置重新统计；
- `_ProxyHandler`：转发 Range、注入 `X-Emby-Authorization`/UA，转发上游响应。
- **注意**：
  - 上游请求使用 `client.proxy_manager.proxies_for(upstream)`；
  - 不要去掉认证头注入，否则 Cloudflare 403；
  - 缓冲窗口只在 `/media/` 请求上统计；
  - 服务是 daemon 线程，`stop()` 在退出/重登时调用。

### `embyqt/imagecache.py`

- `ImageStore`：
  - `QNetworkAccessManager` + 20s transfer timeout；
  - `QNetworkDiskCache`（512MB）+ 内存 LRU；
  - `_DynamicProxyFactory`：每个图片请求按 `ProxyManager` 当前状态返回代理；
  - `load(url, size, callback, radius, crop)`：异步加载，失败回退占位图；
  - `clear_memory()` / `clear_disk()`。
- **注意**：
  - 不要用 `setProxy` 固定代理，否则中途开关系统代理不生效；
  - 图片 URL 可能带 tag/maxWidth，不要打印完整 URL 到 INFO 日志；
  - 占位图逻辑在 `paintEvent`，改样式时同时看 `theme` 的颜色。

### `embyqt/player.py`

- `MpvEngine`（`embyqt/mpv_player.py`）：默认内核，libmpv + Qt QOpenGLWidget render API；
  缓冲读取 `demuxer-cache-time`，`cache-secs` 默认 60 秒。
- `VlcEngine`：libVLC 回退封装。
  - 事件：`ended`、`failed(str)`、`frame_ready(bytes,w,h,pitch)`；
  - 渲染：`attach(win_id)`（X11 `set_xwindow` / macOS `set_nsobject` / Windows `set_hwnd`；macOS 实际走 vmem）、
    `attach_vmem(w,h)`（Wayland 内存回调）；
  - 控制：`play/stop/release/set_pause/is_playing/time_ms/length_ms/set_time/
    set_volume/set_mute`；
  - 轨道：`audio_tracks/set_audio_track/current_audio_track`、
    `subtitle_tracks/set_subtitle_track/current_subtitle_track`、
    `add_external_subtitle`；
  - 字幕延迟：`subtitle_delay/set_subtitle_delay`；
  - `snapshot(path)`。
- `PlaybackReporter`：后台上报 start/progress/stop；单个 daemon 线程 + 队列串行执行，`shutdown()` 入队 None 退出。
- **注意**：
  - Linux 必须 `set_xwindow`，`set_hwnd` 会让 vout=none（有声音没画面）；
  - vmem 回调是 RV32，Qt 侧 `QImage` 直接引用 bytes，必须保持 buffer 引用；
  - `EMBYQT_VLC_ARGS` 可追加 VLC 参数（排障用）；
  - 停止/切换媒体时避免旧 reporter/旧回调串台（`_load_seq` 在窗口层处理）。

### `embyqt/async_task.py`

- `run_async(fn, *args, on_done=None, on_error=None, **kwargs)`：
  QThreadPool + QRunnable，结果通过 Qt 信号回 UI 线程。
- **注意**：
  - 任何网络/耗时操作都用它，不要在主线程 sleep/requests；
  - `on_done/on_error` 在 UI 线程执行；
  - `EMBYQT_DEBUG=1` 时会打印任务异常堆栈。

### `embyqt/context.py`

- `AppContext`：`config / client / proxy / proxy_manager / images`；
- 图片地址辅助：`poster_url/thumb_url/backdrop_url/person_url`；
- 用户数据辅助：`is_played/resume_ticks/progress_fraction`；
- `net_proxy` 属性每次访问都会走 `ProxyManager.current()`。
- **注意**：新增页面时通过 `ctx` 获取依赖，不要自己 new client/store。

---

## 3. UI 基础层

### `embyqt/ui/theme.py`

- `DARK` / `LIGHT` 调色板；模块级颜色常量（`BG/TEXT/ACCENT/...`）；
- `build_stylesheet(p)`：所有 QSS；
- `set_scheme(name)` / `apply(app, name)` / `apply_preference(app, mode)`；
- `system_scheme(app)`：`QStyleHints.colorScheme()` + 调色板亮度回退；
- `PREFERENCE` 全局当前偏好。
- **注意**：
  - 新增控件优先用 `objectName` + QSS，不要硬编码颜色；
  - 自绘组件在 `paintEvent` 读取模块级颜色常量，主题切换后需要 `update()`；
  - `QToolTip` 已统一为 10px / 2×6 padding，主题感知（QSS + palette 双保险）；
  - 窗口圆角 16px 在 QSS + 播放器代码中都有，改动要全局搜 `16px` / `16`。

### `embyqt/ui/icons.py`

- `icon(name, size=22)`：优先渲染 `assets/icons/*.svg`，失败回退 `_draw`。
- `_SVG_FILES`：名称 → 文件映射（play/pause/back10/forward10/volume/muted/
  audio/subtitle/fullscreen/restore）。
- 颜色注入：把 `fill="#eef2fb"` 写入 SVG 根节点；QtSvg 渲染。
- **注意**：
  - 新增图标：下载 SVG → 加入映射 → 在 `ControlBar` 使用；
  - 图标颜色随主题：深色主题浅色图标，浅色主题深色图标；
  - 素材许可：Material Symbols，Apache 2.0，保留 LICENSE/NOTICE。

### `embyqt/ui/branding.py`

- `app_icon()`：程序图标（QIcon）；登录框/标题栏/窗口共用。

### `embyqt/ui/titlebar.py`

- `Sidebar`：侧边栏；左下角用户名按钮弹出菜单（设置/退出登录）。
- `TitleBar`：42px 自绘标题栏（可拖动/双击最大化/最小化/关闭）；`show_tooltips=False` 时播放器不显示悬停提示。
- 信号：`minimize_requested / maximize_requested / close_requested`；
- `set_title()`、`set_rounded()`、`set_maximized()`；
- 拖动 `startSystemMove`；双击最大化。
- **注意**：`set_maximized` 同时设置 QSS `maximized` 属性（切平圆角）；
  播放器最大化/还原依赖它。

### `embyqt/ui/frameless.py`

- `ResizeHandle`：透明热区，按下调用 `window().windowHandle().startSystemResize(edges)`；
- `create_resize_handles(window)` / `position_resize_handles(window, handles)`。
- **注意**：主窗口与播放器共用；最大化/全屏时隐藏。

### `embyqt/ui/widgets.py`

通用 UI 组件，修改频率高：

| 类 | 作用 | 注意 |
| --- | --- | --- |
| `FlowLayout` | 流式布局（媒体库网格） | 需实现 `heightForWidth` |
| `ElidedLabel` | 自动省略文本 | 标题栏/卡片标题 |
| `Chip` | 标签 | 详情页类型/年份 |
| `SectionHeader` | 行标题 + “查看全部” | 信号 `link_clicked` |
| `EmptyState` | 空状态 | 搜索/库 |
| `PosterImage` | 海报图 + 懒加载 + hover | 主题颜色、圆角 |
| `PosterCard` | 海报卡 + 右键菜单 | `activated/play_requested/command` |
| `HScrollArea` | 横向滚动 | `set_wheel_mode("page"/"row")`；page 模式垂直滚轮交还页面；Shift+滚轮/横向手势始终横滚；`WHEEL_FACTOR=3` |
| `PosterRow` | 一行海报 + 标题 + 更多 | `fill=True` 自适应铺满/居中；`set_items()` |
| `PersonCard` / `PersonRow` | 圆形头像/演职人员 | 圆形裁剪 |
| `EpisodeRow` | 剧集条目 | 缩略图/进度/简介 |

- **注意**：
  - 横向列表的滚轮行为由设置项 `ui/wheel_mode` 控制（page/row）；page 模式下垂直滚轮必须 `ignore()` 让外层页面滚动；
  - `PosterRow.fill` 在窗口 resize 后 150ms 防抖重算；
  - 卡片图片按可见性懒加载，避免首页一次请求上百张。

---

## 4. 页面与主窗口

### `embyqt/ui/mainwindow.py`

- `Sidebar`：导航（首页/搜索/收藏/媒体库/设置）、服务器、用户、版本号。
- `MainWindow`：
  - 无边框窗口装配：`windowRoot` → `windowFrame` → `TitleBar` + body；
  - 页面缓存 `_pages`、详情栈 `_detail_pages`、`_current_key`；
  - 会话校验 `_check_session()`、过期 `_expire_session()`；
  - 播放器单实例 `_player` + `_play_item()` + `_on_player_closed()`；
  - 打开/关闭详情、刷新当前页、快捷键、退出。
- **注意**：
  - `_play_item` 里先判断 `self._player` 是否可复用；
  - 播放器 `closed` 信号必须清 `_player`，否则关窗后无法再开；
  - 新页面在 `_ensure_page()` 注册，并接 `open_item/play_item` 信号；
  - 无边框状态切换通过 `_apply_window_state()`，改圆角/边距要同步这里。

### `embyqt/ui/login.py`

- `LoginDialog`：服务器地址 + 端口、用户名/密码、记住登录、探测服务器名。
- 无边框 + 16px 圆角 + `TitleBar`（只有关闭）。
- `_probe_server()`：后台请求 `System/Info`；`_do_login()` 后台登录。
- **注意**：
  - 密码不写入配置；remember 只保存 token；
  - 失败提示不要包含密码/token；
  - 登录成功后 `self.client` 交给 `main`，dialog `accept()`。

### `embyqt/ui/home.py`

- `HeroBanner`：背景 + 标题/元信息 + 播放/详情按钮；
- `HomePage`：继续观看（12）+ 每个媒体库“最新”（24）+ 重试；
- **注意**：
  - `_rows[view_id]` + `_latest_by_view` 缓存；
  - 行使用 `PosterRow(fill=True)`，宽屏自适应铺满；
  - `load(force=True)` 的重试要避免重复请求。

### `embyqt/ui/detail.py`

- `DetailHeader`：简介使用富文本 `line-height:150%`、顶部对齐、最大高度 132px，避免首/末行被垂直裁切；最多约 6 行。

- `DetailHeader`：
  - 背景/海报/标题/元信息/类型/评分/收藏/已看；
  - 版本下拉（`update_sources` / `current_source_id` / `version_changed`）；
  - “播放/继续播放”按钮。
- `DetailPage`：
  - `_on_item`：剧集信息、版本、演职人员；
  - `_on_seasons` / `_load_episodes` / `_on_episodes`：季切换、剧集列表；
  - 分页：`_page_size = 30`，上下分页器，自动跳到第一个未看；
  - `episode_playlist(item)`：返回 `(playlist, index)` 给播放器自动连播；
  - `media_source_id_for(item)`：给 `MainWindow._play_item` 取版本；
  - `refresh()`：收藏/已看后刷新。
- **注意**：
  - 详情页是栈式打开，返回是 `Alt+←`/返回文字；
  - 剧集分页不要一次渲染 1000 集；
  - 版本选择要同时影响播放和“继续播放”位置。

### `embyqt/ui/library.py`

- `LibraryPage`：媒体库网格/列表、类型/年份/排序/升降序、滚动分页；
  「我的收藏」传 `show_genre=False`，不显示“全部类型”下拉；海报横向间距统一 24px。
  窗口变化时按 viewport 宽度减去 30px 内容右内边距计算列数，并在 162–230px 内调整卡片宽度；
  页面右侧不留外边距，竖向滚动条贴窗口右缘，卡片仍保留 30px 呼吸空间。
- `PAGE_SIZE = 60`；`_on_scroll` 触底加载；`_fill_viewport` 视口不足时补加载。
- `_on_command` 处理右键菜单（播放/详情/已看/收藏）。
- **注意**：
  - 过滤条件变化要重置分页；
  - 网格使用 `FlowLayout`，不要用固定列数的 QGridLayout；
  - 加载期间避免重复请求（`_loading` 标志）。

### `embyqt/ui/search.py`

- `SearchPage`：搜索框 + 类型筛选（全部/电影/剧集/单集/合集）+ 结果网格。
- 防抖 + `run_async`；空输入清空结果。
- **注意**：不要按每个按键发请求；结果回来时要丢弃过期请求（当前用输入/筛选判重）。

### `embyqt/ui/settings.py`

- `SettingsPage`：
  - 服务器/名称/用户/代理/设备/版本；
  - 主题三档 combo（`_on_theme_changed`）；
  - 日志开关 + INFO/DEBUG combo（`_on_logging_toggled/_on_level_changed`）；
  - 日志文件路径；
  - 清图片缓存/重新登录/退出登录。
- **注意**：
  - 主题切换调用 `theme.apply_preference(QApplication.instance(), mode)`；
  - 日志切换调用 `logging_setup.configure(...)`，立即生效；
  - 设置控件不要在初始化时触发保存（先 set，再 connect）。

### `embyqt/ui/playerwindow.py`

最大的 UI 文件，包含：

- `VideoSurface`：
  - libVLC 回退路径：`native`（X11/Windows 原生）或 vmem（Wayland/macOS）；
  - libmpv 路径：`MpvVideoSurface`（QOpenGLWidget）通过 render API 绘制，所有平台统一；
  - `paintEvent` 画帧 + 底部圆角裁剪；所有模式都用 mask 裁底部圆角（比控制栏大 4px），避免黑边；
  - 鼠标单击（带横向位置比例，220ms 延迟以区分双击）/双击/移动信号。
- `ProgressSlider`：自绘进度条（轨道/缓冲/手柄/已播放颜色均读取当前主题）；
  灰色区间显示网络缓冲范围；缓冲很小时轨道上方另有细线表示播放头前方的真实缓冲；控制栏实时显示“缓冲 XXs”；支持点击/拖动任意位置定位（`mousePress/Move/Release`）。
  `PlayerWindow._update_buffer()` 每 500ms 从 `StreamProxy.windows_for()` 刷新缓冲区间。
- `PauseOverlay`：暂停时中心半透明圆 + 暂停条。
- `VolumePopup`：悬停音量图标时浮出的垂直音量滑条（58×178），主题感知；
  进入按钮显示，离开按钮/浮层 260ms 后隐藏；
- `LoadingOverlay`：加载时中心 160px 转圈 + 下方网速；`set_speed(bps, direct)`，
  数据来自 `StreamProxy.bytes_for()`；首帧/开始播放后隐藏。
- `ControlBar`：
  - 图标按钮（Material Symbols，24px；按钮 36×36，播放 40）；播放器内不设置 tooltip；
  - 进度/时间/音量；
  - 自动隐藏计时由 `PlayerWindow` 控制；
  - 悬停音量按钮弹出 `VolumePopup`（垂直滑条），点击仍切换静音；
  - 声道/网速图标在音量按钮右侧，speed 图标 24px，`_update_speed()` 更新；
  - 当前/总时间标签固定 60px、居中；
  - `ProgressSlider` 支持点击即定位，并绘制灰色已缓冲区间；
  - `update_play_icon/update_volume_icon/update_fullscreen_icon`。
- `PlayerWindow`：
  - 生命周期：`_load` → `playback_info` → `_on_playback_info` → `_start_stream`；
  - 单实例切换：`play_item()`；
  - 代理：`_start_stream` / `_retry_with_proxy`；
  - 控制：`toggle_pause/seek_relative/on_seek_*/set_volume/toggle_mute`；
  - 单击视频：切换暂停/继续；双击全屏；只有进度条点击/拖动会 seek；
  - 窗口：`toggle_fullscreen/_toggle_maximized/_apply_window_state`；
  - 自动隐藏：`_show_controls/_maybe_hide_controls`；
  - 音轨/字幕菜单、外挂字幕、自动下一集、关闭上报。
- **注意**：
  - `_loading` 防旧回调/旧 ended；
  - `_load_seq` 防旧 `PlaybackInfo` 串台；
  - `play_item` 复用窗口时先 `engine.stop()` 并清空旧帧；
  - 不要用 `setText` 更新播放/音量/全屏按钮（已是图标）；
  - 控制栏自动隐藏只应在播放中隐藏，暂停保持可见；
  - 布局时序：`resizeEvent` 里先 `_outer.activate()` 再 `_layout_media()`，并 `QTimer.singleShot(0, ...)` 补一次。

---

## 5. 模块交互速查

```text
MainWindow
  ├─ ctx.client (api)       ── 数据
  ├─ ctx.images (imagecache)── 海报
  ├─ ctx.proxy (streamproxy)── 播放流/网速
  ├─ ctx.proxy_manager (net)── 所有请求代理
  ├─ ctx.config (config)    ── 设置
  └─ PlayerWindow (playerwindow)
        └─ VlcEngine (player) + PlaybackReporter
```

- 页面只发信号，不直接播放/跳转；
- `MainWindow` 负责路由、详情栈、播放器生命周期；
- `PlayerWindow` 负责播放状态和窗口行为；
- `AppContext` 是依赖注入容器，新增全局服务优先放这里。

---

## 6. 新增文件时

1. core 层放在 `embyqt/`，UI 层放在 `embyqt/ui/`；
2. 更新 `docs/MODULES.md` 的对应章节；
3. 如果影响启动/数据流，更新 `docs/PROJECT.md`；
4. 如果影响 AI 改代码方式，更新 `docs/LLM_GUIDE.md`；
5. 加测试（纯逻辑放 `tests/`）。


### libmpv 缓冲 API

- `cache-buffering-state`：0–100 缓冲百分比；
- `paused-for-cache`：是否因缓存不足暂停；
- `demuxer-cache-duration`：当前缓存时长（秒）；
- `demuxer-cache-time`：缓存末端时间戳；
- `demuxer-cache-state.seekable-ranges`：可 seek 缓存区间，用于进度条灰色段；
- `cache-pause` / `cache-pause-wait` / `cache-pause-initial`：缓存不足自动暂停策略；
- `demuxer-readahead-secs`：预读时长。


- libmpv 缓存目标：
  - 有限大小：`缓存字节数 / MediaSource.Size * 影片时长`；
  - `不限`：使用整部影片时长；
  - 大小未知时回退 `EMBYQT_MPV_CACHE_SECS`；
  - `cache-buffering-state=100%` 只表示 mpv 认为缓存状态健康，不代表缓存目标已填满；界面改为显示“当前缓存 / 目标缓存”时长。


- 设置页「缓冲大小」写入 `player/cache_bytes`，映射到 libmpv `demuxer-max-bytes`；
  0 表示不限，下次打开播放器时生效。
