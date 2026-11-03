# EmbyQt 文档

本目录是 EmbyQt 的长期维护文档，面向两类读者：

1. **维护者**：需要改功能、修 bug、发布版本的人；
2. **大模型 / AI 编码助手**：需要在较少上下文下快速定位文件、理解约束、做出安全修改。

> 文档与代码保持一致；如果修改了行为，请同步更新对应文档（至少 `LLM_GUIDE.md` 与相关模块说明）。

## 文档地图

| 文档 | 内容 | 什么时候读 |
| --- | --- | --- |
| [PROJECT.md](PROJECT.md) | 项目定位、硬约束、技术栈、启动/播放/代理数据流、目录结构、设计决策 | 第一次接触项目 |
| [MODULES.md](MODULES.md) | 核心层与 UI 层逐模块说明：职责、关键类/函数、依赖、修改注意点 | 定位到某个文件前后 |
| [EMBY_API.md](EMBY_API.md) | 用到的 Emby REST 接口、认证头、DirectPlay、播放上报、图片/字幕地址、错误处理 | 改接口、调播放、排查 403 |
| [MAINTENANCE.md](MAINTENANCE.md) | 环境、命令、常见改动配方、调试手册、发布检查清单 | 日常开发/排障 |
| [LLM_GUIDE.md](LLM_GUIDE.md) | 给 AI 的最短上下文：不变式、文件地图、任务→文件、验证清单、常见错误 | 让模型快速改代码 |

## 一句话介绍

**EmbyQt** 是一个基于 Emby REST API 的桌面媒体客户端：PySide6 无边框界面、自绘标题栏、深/浅色主题、
libVLC 内嵌播放、单实例播放器、系统代理自动跟随，面向“服务器只允许 DirectPlay”的场景。

## 快速事实

| 项 | 值 |
| --- | --- |
| 包名 / 版本 | `embyqt` / `1.1.0`（`embyqt/__init__.py`） |
| 入口 | `./run.sh` → `python -m embyqt` → `embyqt/main.py:main()` |
| UI 框架 | PySide6 6.12（Essentials），Qt 6 |
| 播放 | python-vlc / libVLC 3（Wayland vmem 渲染，X11 原生嵌入） |
| 网络 | requests + 自研 `ProxyManager`（默认 2 秒 TTL）+ 本机 StreamProxy |
| 配置 | `QSettings("EmbyQt", "EmbyQt")`，Linux 下即 `~/.config/EmbyQt/EmbyQt.conf` |
| 日志 | 默认开启、默认 `DEBUG`；终端 + 轮转文件 |
| 主题 | 跟随系统 / 深色 / 浅色，运行中即时切换（蓝色强调色） |
| 窗口 | 无边框 + 自绘标题栏，统一 **16px** 圆角，最大化/全屏切平 |
| 播放器 | **全局唯一**；再次点播在同一窗口切换；窗口模式 10 秒无操作隐藏控制栏 |
| 测试 | 60 个单元测试（`tests/`） |
| 平台 | Linux（Wayland 默认）为主；Windows/macOS 代码路径已预留，待实机验证 |

## 维护者阅读顺序

1. `PROJECT.md`：先弄清“为什么只能 DirectPlay”“为什么必须在每个请求前判断代理”；
2. `MODULES.md`：按文件了解职责；
3. `MAINTENANCE.md`：按配方改代码、跑测试；
4. `EMBY_API.md`：涉及服务器行为时查阅。

## AI 阅读顺序

1. `LLM_GUIDE.md` 的“不变式”和“文件地图”；
2. 目标文件在 `MODULES.md` 中的条目；
3. 需要改动的具体函数；
4. 按 `LLM_GUIDE.md` 的验证清单执行。

## 文档维护约定

- 新增文件 / 类 / 信号：更新 `MODULES.md`；
- 新增配置项 / 环境变量 / 快捷键：更新 `PROJECT.md` 与 `MAINTENANCE.md`；
- 新增接口或改变播放策略：更新 `EMBY_API.md` 与 `LLM_GUIDE.md`；
- 改变 UI 常量（圆角、图标尺寸、自动隐藏时间）：更新 `PROJECT.md`、`LLM_GUIDE.md` 与 `README.md`；
- 发布前：确认文档没有过期描述，特别是“已知限制”和“默认值”。
