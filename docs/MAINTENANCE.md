# EmbyQt 维护指南

## 1. 环境准备

```bash
cd emby-qt
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

依赖：

- Python 3.14（已验证；使用 3.10+ 的类型注解写法）
- PySide6-Essentials（Qt 6）
- python-vlc + 系统 libVLC 3
- requests

Linux 额外说明：

- 需要可用的 libVLC；
- 如果 Qt xcb 后端缺 `libxcb-cursor.so.0`，仓库 `vendor/lib/` 提供副本，`run.sh` 会自动加入
  `LD_LIBRARY_PATH`；
- 默认使用 Qt 原生 Wayland；只有明确需要 X11 原生视频嵌入时才：

```bash
EMBYQT_FORCE_X11=1 ./run.sh
```

## 2. 常用命令

| 目的 | 命令 |
| --- | --- |
| 启动 | `./run.sh` |
| 单元测试 | `PYTHONPATH=. .venv/bin/python -m unittest discover -s tests` |
| 只跑某个测试 | `PYTHONPATH=. .venv/bin/python -m unittest tests.test_net` |
| 语法编译检查 | `.venv/bin/python -m compileall -q embyqt scripts tests` |
| 服务器能力探测 | `EMBY_USER=... EMBY_PASS=... .venv/bin/python scripts/check_server.py` |
| UI 冒烟/截图 | `EMBY_USER=... EMBY_PASS=... PYTHONPATH=. .venv/bin/python scripts/smoke_ui.py` |
| 播放冒烟 | `EMBY_USER=... EMBY_PASS=... PYTHONPATH=. .venv/bin/python scripts/smoke_player.py` |
| 查看日志（Linux） | `tail -f ~/.local/state/embyqt/logs/embyqt.log` |

> 测试脚本会优先读取 `.probe/login.json`，否则用 `EMBY_USER/EMBY_PASS` 登录。
> 不要把账号、密码、token 提交到仓库或写进文档/截图。

## 3. 调试开关与环境变量

| 变量 | 作用 |
| --- | --- |
| `EMBYQT_PROXY` | 覆盖代理；`none/off/direct` 强制直连 |
| `EMBYQT_THEME` | 启动时临时覆盖主题：`dark/light/system` |
| `EMBYQT_FORCE_X11=1` | Wayland 会话下强制 xcb（仅排障/需要原生视频时） |
| `EMBYQT_VLC_ARGS` | 追加 libVLC 参数，如 `--verbose=2` |
| `EMBYQT_DEBUG=1` | `run_async` 打印任务异常堆栈 |
| `EMBYQT_DEBUG_IMAGES=1` | 图片加载打印状态/字节数 |
| `QT_QPA_PLATFORM` | Qt 平台插件；不要随意设成 `xcb` |
| `QT_LOGGING_RULES` | 程序会追加 `qt.qpa.wayland.textinput=false` |

日志级别和开关不需要环境变量，直接在「设置 → 日志」改，立即生效。

## 4. 常见改动配方

### 4.1 新增一个 Emby API 调用

1. 在 `embyqt/api.py` 的 `EmbyClient` 里加方法；
2. 一律通过 `self._request("GET"/"POST", path, params=..., json=...)`；
3. 需要新字段时，把字段加进 `GRID_FIELDS / DETAIL_FIELDS / EPISODE_FIELDS` 或调用处 `Fields`；
4. 解析用 `.get()`，对缺失字段给默认值；
5. 日志用 `get_logger("api")`，不要打印 token/header；
6. 加单元测试（可用 `tests/test_api.py` 的 URL 构造测试模式）。

### 4.2 新增一个页面

1. 新建 `embyqt/ui/<page>.py`，继承 `QWidget`，暴露 `open_item/play_item` 等信号；
2. 在 `MainWindow._ensure_page()` 注册 key；
3. 在 `Sidebar` 里加导航按钮（媒体库是动态的，静态入口按需加）；
4. 页面通过 `self.ctx` 获取 client/images/config，不要自己建；
5. 网络请求用 `run_async`；
6. 更新 `MODULES.md` 的页面表。

### 4.3 新增一个设置项

1. `embyqt/config.py` 加 property（带默认值和校验）；
2. `embyqt/ui/settings.py` 加控件；
3. **先 set 值，再 connect**，避免初始化时触发保存；
4. 应用逻辑（主题/日志/播放器）在变更回调里立即执行；
5. 更新 `PROJECT.md` 的配置表和 `LLM_GUIDE.md`（如果 AI 需要知道）。

### 4.4 改窗口圆角

统一是 **16px**，但分散在多处，改之前全局搜索：

```bash
grep -R "16px\|set_corner_radius\|_corner_radius\|radius = 16" embyqt
```

需要同步：

- `theme.py`：`windowFrame / loginFrame / playerFrame / titleBar / windowStatus`；
- `playerwindow.py`：`VideoSurface._corner_radius`、`_apply_window_state()` 的 `set_corner_radius`、
  `ControlBar._apply_style()`；
- `README.md` 与 `docs/PROJECT.md` 的 16px 描述；
- 重新生成截图。

### 4.5 改播放器控制栏图标/大小

1. 图标文件放 `embyqt/assets/icons/`，并在 `icons._SVG_FILES` 加映射；
2. 用 `icons.icon("name")`；
3. `ControlBar._icon_button()` 控制按钮尺寸；当前图标 24px、按钮 36×36（播放 40）；
   音量浮层在 `VolumePopup`，悬停音量按钮显示；
4. 不要改回文字按钮；
5. 保留 SVG 许可文件。

### 4.6 改控制栏/进度条自动隐藏

逻辑在 `PlayerWindow`：

- `_hide_timer`：单次计时；
- `_show_controls()`：显示并重启计时（播放中）；
- `_maybe_hide_controls()`：播放中/非拖动/无错误时隐藏；
- `_on_mouse_moved()` / `ControlBar.mouseMoveEvent`：恢复；
- 窗口模式 10 秒，全屏 2.6 秒。

修改时间时同步 `_apply_window_state()` 里的 interval 和文档。

### 4.7 改代理逻辑

- 探测：`net.detect_proxy()`；
- 缓存/复查：`ProxyManager`（TTL 2s）；
- API：`EmbyClient._request` 里 `proxies_for(url)`；
- 图片：`imagecache._DynamicProxyFactory.queryProxy`；
- 播放：`StreamProxy` 上游请求；
- 播放开始/登录/设置页：`force_refresh()`。

**不要**在某个模块里单独 `requests.get(..., proxies=...)` 或 `QNetworkProxy.setProxy` 固定代理，
否则会出现“部分请求走代理、部分直连”。

### 4.8 改播放流程/增加版本选择

- 入口：`MainWindow._play_item()`；
- 播放信息：`PlayerWindow._on_playback_info()`；
- 流地址：`_start_stream()`；
- 直连/代理回退：`_retry_with_proxy()`；
- 版本：`DetailPage.media_source_id_for()` 一路透传；
- 单实例：`play_item()` 复用窗口；
- 结束/下一集：`_on_ended()/_play_next()`；
- 改完用真实媒体做一次冒烟（`scripts/smoke_player.py`）。

### 4.9 改主题颜色

1. `theme.DARK/LIGHT` 加/改 token；
2. `build_stylesheet()` 里用 `p['token']`；
3. 自绘组件（海报占位、进度条、按钮 hover）读取模块级颜色常量；
4. 深/浅两套都要看；
5. 截图更新。

### 4.10 加日志

```python
from embyqt.logging_setup import get_logger
log = get_logger("api")   # 或 player/ui/net/login/settings
log.info("...")
log.debug("...")
```

- 不记录密码/token/Authorization；
- 高频路径用 DEBUG，用户可见事件用 INFO，失败用 WARNING/ERROR；
- 默认 DEBUG，发布前可把默认级别改成 INFO（在 `Config.logging_level`）。

## 5. 测试与验证

### 5.1 自动测试

```bash
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
```

当前覆盖：

- `tests/test_api.py`：URL 构造、服务器地址/端口、流地址；
- `tests/test_net.py`：代理解析、bypass、PAC、ProxyManager 缓存/变化；
- `tests/test_theme.py`：调色板、QSS 构建、主题切换；
- `tests/test_streamproxy.py`：下载字节累计、播放会话重置（仅用于网速）。

### 5.2 手工验证清单

改动后至少检查：

- [ ] `./run.sh` 能出窗口，不是“进程在跑但看不到”；
- [ ] 登录（或已有 token）正常，首页媒体库/海报出来；
- [ ] 打开详情、切换版本、剧集分页；
- [ ] 点播 A，再点播 B：同一个播放器窗口切换；
- [ ] 暂停出现中心遮罩，继续播放消失；
- [ ] 窗口模式 10 秒无操作控制栏隐藏，移动鼠标恢复；
- [ ] 全屏/最大化/还原圆角正确；
- [ ] 前进/后退 10 秒、音量、静音、音轨、字幕菜单可用；
- [ ] 浅色/深色/跟随系统切换正常；
- [ ] 设置里日志开关/级别生效（看终端/文件）；
- [ ] 退出/重新登录不崩。

### 5.3 截图

README 的截图位于 `docs/screenshot-*.png`。UI 改动后重新生成，避免文档与界面不一致。

## 6. 调试手册

### 6.1 执行 run.sh 后没反应

1. 看终端是否有 `[EmbyQt] 已打开主窗口` / `打开登录窗口`；
2. 如果没有，检查日志（默认 DEBUG）和 `Traceback`；
3. 如果进程在但看不到窗口：
   - 确认没有设置 `QT_QPA_PLATFORM=xcb`；
   - 本机 `DISPLAY=:0` 可能不是桌面显示；
   - 用默认 Wayland，不要强制 xcb。

### 6.2 403 请使用群公告中允许的客户端

- 确认请求走 `EmbyClient._request`（带头）；
- 确认 `CLIENT_NAME` 未被改；
- 播放确认走 StreamProxy（有系统代理时）或失败回退；
- 不要用只有 `api_key` 的 URL 测播放器。

### 6.3 有声音没画面

- Linux 必须 `set_xwindow`，不能 `set_hwnd`；
- 检查是否走了 vmem（Wayland）但 `frame_ready` 没连上；
- X11 原生嵌入：`EMBYQT_FORCE_X11=1`；
- 用 `EMBYQT_VLC_ARGS="--verbose=2"` 看 VLC 日志。

### 6.4 代理相关

- 设置页看当前代理；
- `EMBYQT_PROXY=none ./run.sh` 验证直连；
- 代理没启动会失败；日志里有 `系统代理已变更`；
- 注意 2 秒 TTL：切换代理后最多 2 秒生效；播放开始/登录会强制刷新。

### 6.5 图片不显示

- `EMBYQT_DEBUG_IMAGES=1` 看状态；
- 检查图片 URL 是否需要代理；
- 清「设置 → 清除图片缓存」；
- 服务器图片接口可能慢，首次会占位。

### 6.6 主题切换无效

- 设置页选择后看 `theme.SCHEME`；
- 自绘组件是否在主题变化后 `update()`；
- QSS 是否用了硬编码颜色（应使用 `p['...']`）；
- 系统模式依赖 `QStyleHints.colorScheme()`，Linux 读不到时用调色板亮度回退。

### 6.7 控制栏一直不隐藏/一直隐藏

- 只有播放中才隐藏；暂停保持可见；
- 10 秒窗口模式、2.6 秒全屏；
- 检查 `_hide_timer` 是否被 `_show_controls()` 重启；
- 鼠标移动事件是否到达（`VideoSurface.mouse_moved` / `ControlBar.mouseMoveEvent`）。

### 6.8 日志文件写不进去

- 路径见「设置 → 日志文件」；
- 目录不可写时自动退回仅终端；
- 用 `XDG_STATE_HOME` 指定可写目录测试。

## 7. 发布检查清单

- [ ] `embyqt/__init__.py` 版本号更新；
- [ ] `README.md` 功能/截图更新；
- [ ] `docs/` 中受影响的文档更新；
- [ ] 60 个测试通过，`compileall` 通过；
- [ ] 真实媒体播放冒烟（分段/跳转/下一集/字幕）；
- [ ] 深色/浅色/跟随系统各看一遍；
- [ ] 日志默认级别确认（发版前默认 DEBUG；正式包可按需改 INFO）；
- [ ] 仓库扫描确认没有真实密码/token（至少执行 `grep -R "EMBY_PASS" .` 并人工检查）；
- [ ] `embyqt/assets/icons/LICENSE` 与 `NOTICE` 存在；
- [ ] 不提交 `.venv/`、`.cache/`、`.config/`、`.probe/`、`docs/_*.png`；
- [ ] 打包/运行依赖包含 libVLC。

## 8. 代码约定

- UI 文案中文；代码标识符英文；
- 类型注解 + `from __future__ import annotations`；
- 类/信号命名：`XxxPage`、`XxxRequested`；
- 网络/耗时操作只走 `run_async`；
- 错误提示面向用户，日志面向排障；
- 新增依赖先讨论，优先使用 Qt/Python 标准能力；
- 不要引入会阻塞启动的网络调用；
- 不要把业务逻辑写进 `paintEvent`。

## 9. 已知坑（高频）

1. **建窗前网络请求** → 启动“卡住”；
2. **Wayland 强制 xcb** → 窗口不可见；
3. **Linux 用 set_hwnd** → 有声音没画面；
4. **代理只在启动判断** → 中途切换失效；
5. **QNAM setProxy 固定** → 图片不跟随代理变化；
6. **多播放器实例** → 重复点播开多窗；
7. **改圆角只改一处** → 标题栏/视频/控制栏不齐；
8. **改主题漏掉自绘组件** → 深色/浅色混搭；
9. **控制栏自动隐藏逻辑写反** → 暂停时也隐藏，无法操作；
10. **日志打印 token** → 安全风险。
