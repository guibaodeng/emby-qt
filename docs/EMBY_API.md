# Emby API 使用说明（本项目相关部分）

> 目标服务器在 Cloudflare 后，并按客户端名称做白名单校验。本文只描述本项目实际用到的接口，
> 不是完整的 Emby API 文档。服务器版本在编写时约为 4.9.5.0，接口以代码为准。

## 1. 基础约定

### 1.1 地址

- `Config.server` 保存完整 URL（可带反向代理子路径，如 `https://host/emby`）；
- 登录框支持“地址 + 端口”，由 `build_server_url()` 拼接；
- 所有请求地址 = `server + path`。

### 1.2 认证头（必须）

```text
X-Emby-Authorization: MediaBrowser Client="Emby for Android", Device="EmbyQt Desktop", DeviceId="<device-id>", Version="1.1.0", Token="<token>"
```

- `CLIENT_NAME` 必须是服务器白名单放行的名称，代码里是 `"Emby for Android"`；
- 登录前没有 Token；登录后所有请求带 Token；
- **只带 `?api_key=` 的请求会被 Cloudflare 403**，不要用这种方式替代头；
- `X-Emby-Token` 也会带一份（兼容部分 Emby 端点）。

### 1.3 数据类型

- `TICKS = 10_000_000`，即 1 秒 = 10,000,000 ticks；
- 播放位置/时长在 API 中全部用 ticks，在播放器内部用毫秒；
  - `ms → ticks`: `ms * 10_000`
  - `ticks → ms`: `ticks // 10_000`
- `UserData.PlaybackPositionTicks` 是续播位置；`UserData.Played` 是已看标记。

### 1.4 错误与重试

`EmbyClient._request()`：

- GET 与 `/Users/AuthenticateByName` 最多重试 3 次，其余 1 次；
- 遇到 `ProxyError` 会 `proxy_manager.force_refresh()` 后再试；
- 网络错误转换为 `EmbyError`，并给出中文提示（代理/超时/TLS/连接失败）；
- HTTP >= 400 时尝试解析服务器错误 JSON，否则给通用错误；
- `401` 会在主窗口被识别为登录过期。

## 2. 接口清单

| 用途 | 方法 | 路径 | 关键参数 |
| --- | --- | --- | --- |
| 登录 | POST | `/Users/AuthenticateByName` | JSON `{Username, Pw}` |
| 注销 | POST | `/Sessions/Logout` | — |
| 服务器信息 | GET | `/System/Info` | — |
| 当前用户 | GET | `/Users/{userId}` | — |
| 媒体库列表 | GET | `/Users/{userId}/Views` | — |
| 最新 | GET | `/Users/{userId}/Items/Latest` | `ParentId, Limit, Fields` |
| 继续观看 | GET | `/Users/{userId}/Items/Resume` | `Limit, Fields` |
| 条目查询 | GET | `/Users/{userId}/Items` | `ParentId, IncludeItemTypes, StartIndex, Limit, SortBy, SortOrder, SearchTerm, Genres, Filters, Fields` |
| 条目详情 | GET | `/Users/{userId}/Items/{itemId}` | `Fields` |
| 类型/年份 | GET | `/Genres` | `UserId, ParentId, Limit` |
| 搜索 | GET | `/Users/{userId}/Items` | `SearchTerm, IncludeItemTypes, Limit` |
| 季 | GET | `/Shows/{seriesId}/Seasons` | `UserId, Fields` |
| 集 | GET | `/Shows/{seriesId}/Episodes` | `UserId, SeasonId, Fields` |
| 相似 | GET | `/Items/{itemId}/Similar` | `UserId, Limit, Fields` |
| 收藏 | POST/DELETE | `/Users/{userId}/FavoriteItems/{itemId}` | — |
| 已看 | POST/DELETE | `/Users/{userId}/PlayedItems/{itemId}` | — |
| 播放信息 | POST | `/Items/{itemId}/PlaybackInfo` | `UserId`；JSON `DeviceProfile` 等 |
| 开始播放 | POST | `/Sessions/Playing` | `ItemId, MediaSourceId, PlaySessionId, PositionTicks, PlayMethod` |
| 播放进度 | POST | `/Sessions/Playing/Progress` | 同上 + `IsPaused, VolumeLevel, EventName` |
| 停止播放 | POST | `/Sessions/Playing/Stopped` | 同上 |
| 图片 | GET | `/Items/{itemId}/Images/{kind}` | `tag, maxWidth, quality, index` |
| 视频流 | GET | `/Videos/{itemId}/stream` | `static=true, MediaSourceId, PlaySessionId` |
| 字幕 | GET | `/Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/Stream.{fmt}` | — |

### 2.1 常用查询字段

- `GRID_FIELDS`：`ProductionYear,RunTimeTicks,CommunityRating,OfficialRating,ImageTags,BackdropImageTags,UserData`
- `DETAIL_FIELDS`：详情、类型、简介、演职人员、MediaSources/MediaStreams 等
- `EPISODE_FIELDS`：集数、季数、SeriesId/SeasonId、UserData 等

字段是逗号分隔字符串，Emby 不返回未请求的字段；新增 UI 信息时要同步加字段。

## 3. PlaybackInfo 与 DirectPlay

### 3.1 请求体

```json
{
  "UserId": "<userId>",
  "StartTimeTicks": 0,
  "IsPlayback": true,
  "AutoOpenLiveStream": true,
  "MaxStreamingBitrate": 200000000,
  "DeviceProfile": { "...": "..." }
}
```

可选 `MediaSourceId`（多版本时指定）。

### 3.2 DeviceProfile

`EmbyClient.device_profile()` 刻意声明：

- `DirectPlayProfiles`：视频容器/编码、音频容器/编码；
- `TranscodingProfiles = []`、`ContainerProfiles = []`、`CodecProfiles = []`；
- 字幕：srt/subrip/ass/ssa/vtt 外部，pgssub/dvdsub 内嵌。

**不要随意加 TranscodingProfiles**：目标服务器关闭了转码/Remux，请求也不会成功；
客户端只做 DirectPlay。

### 3.3 播放地址

`stream_path()`：

```text
/Videos/{itemId}/stream?static=true&MediaSourceId={sourceId}&PlaySessionId={psid}
```

两条路径：

1. **直连**（无系统代理时优先）：
   `server + stream_path + "&api_key=" + token`，交给 VLC。
   该服务器可能因白名单拒绝 api_key-only 请求；失败时会回退本机代理。
2. **本机 StreamProxy**（有系统代理时固定使用）：
   `http://127.0.0.1:<port>/media/<itemId>?src=...&psid=...`；
   StreamProxy 注入 `X-Emby-Authorization`/UA 后再请求上游，支持 Range 转发和下载字节统计（用于网速）。

### 3.4 字幕

- 内嵌字幕由 VLC 直接选择；
- 外挂字幕通过 `subtitle_path()` 构造，经 `StreamProxy.subtitle_url()` 转发；
- `subtitle_path` 会把 `subrip → srt`、`pgssub → sup`。

## 4. 播放上报

`PlaybackReporter`（`player.py`）在后台线程调用：

- `report_start()`：`/Sessions/Playing`，`PlayMethod="DirectPlay"`；
- `report_progress()`：每 10 秒/暂停/拖动，`EventName="TimeUpdate"`；
- `report_stop()`：关闭/切换/结束时。

字段：`ItemId、MediaSourceId、PlaySessionId、PositionTicks、CanSeek、IsPaused、
IsMuted、VolumeLevel、PlayMethod、PlaylistIndex/Length`。

**注意**：

- 上报失败不应影响播放；
- reporter 关闭时必须 `shutdown()`，避免线程泄漏；
- 切换媒体时先停旧 reporter，再建新的。

## 5. 图片

`image_url()`：

```text
/Items/{itemId}/Images/{kind}?quality=90&tag=...&maxWidth=...
```

- `kind`：Primary / Backdrop / Logo / Thumb / Banner / Art；
- 海报优先 `ImageTags.Primary`；没有则用剧集 `SeriesPrimaryImageTag`；
- 背景没有时回退到海报；
- 图片由 `ImageStore` 异步加载，带 512MB 磁盘缓存和内存 LRU；
- 图片请求同样经过 `ProxyManager`（Qt 的 `QNetworkProxyFactory`），每个请求动态判断。

## 6. 403 与排障

### 6.1 典型 403

```text
403 请使用群公告中允许的客户端进行访问
```

原因：

- 缺少 `X-Emby-Authorization`；
- `CLIENT_NAME` 不在白名单；
- 请求只带 `api_key`（例如直接用 VLC 打开带 `api_key` 的 URL）。

修复：

- API：确保走 `EmbyClient._request`；
- 播放：有系统代理时走 StreamProxy；无代理直连失败时回退 StreamProxy；
- 不要修改 `CLIENT_NAME`，除非服务器白名单同步更新。

### 6.2 401

- token 过期或被注销；
- 主窗口 `_on_user_error` 识别为登录过期，清 session 回登录框。

### 6.3 超时/连接失败

- 检查系统代理（设置页显示当前值）；
- 用 `EMBYQT_PROXY=http://host:port` 临时覆盖；
- 服务器在 Cloudflare 后，首次连接可能 1–3 秒。

## 7. 兼容性建议

- Emby 不同版本字段可能缺失：解析时用 `.get()` 并提供默认值；
- 新增接口时优先复用 `_request()` 和现有字段集合；
- 如果服务器升级导致 `PlaybackInfo` 行为变化，先抓取原始 JSON 对比；
- 不要把服务器版本号写死为契约，代码应以能力/字段判断。
