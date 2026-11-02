# libmpv 迁移计划

基线：`v1.0.0-vlc`（提交 `c881a07`），保留 libVLC 作为回退。

## 目标

- 播放内核切换到 libmpv；
- 保留单窗口、自定义标题栏、Qt 控制栏；
- 利用 libmpv 的 `cache-secs`、`demuxer-max-bytes` 和
  `demuxer-cache-time`/`demuxer-cache-duration` 改善缓冲显示；
- libmpv 不可用时自动回退 libVLC。

## 系统依赖

Linux（Ubuntu/Debian）：

```bash
sudo apt install libmpv2
.venv/bin/pip install python-mpv
```

验证：

```bash
python -c "import mpv; print(mpv.MPV(video=False).mpv_version)"
```

## 播放接口

新增 `PlayerEngine` 抽象，`VlcEngine` 与 `MpvEngine` 实现同一组方法：

```text
play / stop / release / set_pause / is_playing
time_ms / length_ms / set_time / is_seekable
set_volume / volume / set_mute
audio_tracks / set_audio_track / current_audio_track
subtitle_tracks / set_subtitle_track / current_subtitle_track
add_external_subtitle
buffer_ahead_ms / attach / attach_vmem / frame_ready
```

`PlayerWindow` 只依赖抽象，不直接 import vlc/mpv。

## 视频输出

- X11 / Windows / macOS：使用 libmpv `wid` 嵌入原生窗口；
- Wayland：libmpv 没有 VLC vmem 回调，必须使用
  `MpvRenderContext` + `QOpenGLWidget`（OpenGL render API）；
- vmem 路径仅保留给 libVLC 回退。

## 缓冲

- mpv 侧读取 `demuxer-cache-time`（秒）或
  `demuxer-cache-duration`；
- 进度条缓冲区间 = 当前播放位置到
  `播放位置 + cache_time`，不再依赖 StreamProxy 的 HTTP Range 百分比；
- 手动 seek 后直接读取 mpv 的新缓存状态，避免旧窗口残留。

## 分阶段

1. 抽象出 `PlayerEngine`，VLC 全量回归；
2. `MpvEngine` + X11 `wid`，本地播放/音轨/字幕/seek/结束事件；
3. Wayland `MpvRenderContext` + QOpenGLWidget；
4. 缓冲显示接入 mpv cache 属性；
5. 打包脚本加入 libmpv 与 python-mpv，保留 VLC 回退。

## 当前状态

已安装 libmpv，并完成 MpvEngine、Qt OpenGL render API、播放/seek/缓冲显示接入；
libVLC 仍可通过 `EMBYQT_PLAYER=vlc` 回退。
