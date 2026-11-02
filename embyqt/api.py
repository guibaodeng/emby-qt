"""Emby REST API 封装。

所有请求都会带上 ``X-Emby-Authorization`` 头 —— 该服务器在 Cloudflare 层
按客户端名做白名单校验，只带 ``api_key`` 查询参数的请求会被 403。
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlencode, urlsplit

import requests

from . import CLIENT_NAME, CLIENT_VERSION, DEVICE_NAME
from .logging_setup import get_logger
from .net import ProxyConfig, ProxyManager, default_manager

TICKS = 10_000_000
DEFAULT_TIMEOUT = (15.0, 60.0)

GRID_FIELDS = (
    "ProductionYear,RunTimeTicks,CommunityRating,OfficialRating,"
    "ImageTags,BackdropImageTags,UserData"
)
DETAIL_FIELDS = (
    "ProductionYear,RunTimeTicks,CommunityRating,OfficialRating,Overview,"
    "Genres,ImageTags,BackdropImageTags,UserData,People,MediaSources,"
    "MediaStreams,Taglines,ProviderIds,PremiereDate,EndDate,SeriesInfo,"
    "SeriesStudio,ChildCount,RecursiveItemCount,Container"
)
EPISODE_FIELDS = (
    "ProductionYear,RunTimeTicks,CommunityRating,Overview,ImageTags,"
    "BackdropImageTags,UserData,MediaSources,MediaStreams,IndexNumber,"
    "ParentIndexNumber,SeriesId,SeasonId"
)


class EmbyError(Exception):
    """API 调用失败。``status`` 为 HTTP 状态码（网络错误时为 None）。"""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_server(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def build_server_url(address: str, port: str = "") -> str:
    """把「地址 + 端口」拼成规范 URL。

    - 地址可带或不带 scheme，缺省 https；
    - 地址中显式写的端口优先，否则使用 ``port``；
    - 支持反向代理子路径（如 https://host/emby）。
    """
    address = (address or "").strip()
    if not address:
        return ""
    if not re.match(r"^https?://", address, re.I):
        address = "https://" + address
    parts = urlsplit(address)
    host = parts.hostname or ""
    if not host:
        return ""
    scheme = (parts.scheme or "https").lower()
    chosen = parts.port
    if chosen is None and str(port or "").strip():
        text = str(port).strip()
        if not text.isdigit():
            raise ValueError("端口必须是数字")
        value = int(text)
        if not 1 <= value <= 65535:
            raise ValueError("端口超出范围（1-65535）")
        chosen = value
    netloc = f"[{host}]" if ":" in host else host
    if chosen:
        netloc = f"{netloc}:{chosen}"
    path = (parts.path or "").rstrip("/")
    return f"{scheme}://{netloc}{path}"


def image_url(
    server: str,
    item_id: str,
    kind: str = "Primary",
    *,
    index: Optional[int] = None,
    tag: Optional[str] = None,
    max_width: Optional[int] = None,
    quality: int = 90,
) -> str:
    """构造图片地址。kind: Primary / Backdrop / Logo / Thumb / Banner / Art。"""
    if not server or not item_id:
        return ""
    path = f"{server}/Items/{item_id}/Images/{kind}"
    if index is not None:
        path += f"/{index}"
    params: Dict[str, Any] = {"quality": quality}
    if tag:
        params["tag"] = tag
    if max_width:
        params["maxWidth"] = max_width
    return path + "?" + urlencode(params)


class EmbyClient:
    """线程安全的轻量客户端：内部 requests.Session 主要供后台线程使用。"""

    def __init__(
        self,
        server: str,
        device_id: str,
        token: str = "",
        user: Optional[dict] = None,
        proxy: Optional[ProxyConfig] = None,
        proxy_manager: Optional[ProxyManager] = None,
    ) -> None:
        self.server = normalize_server(server)
        self.device_id = device_id or "embyqt"
        self.token = token or ""
        self.user: Dict[str, Any] = user or {}
        if proxy_manager is not None:
            self.proxy_manager = proxy_manager
        elif proxy is not None:
            self.proxy_manager = ProxyManager(static_config=proxy)
        else:
            self.proxy_manager = default_manager()
        self._session = requests.Session()
        # 代理完全由 ProxyManager 决定，不允许 requests 再读环境变量
        self._session.trust_env = False

    @property
    def proxy(self) -> Optional[ProxyConfig]:
        """当前生效的代理（每次访问都会按 TTL 复查）。"""
        return self.proxy_manager.current()

    # ---- 认证 -----------------------------------------------------------
    @property
    def user_id(self) -> str:
        return str(self.user.get("Id") or "")

    @property
    def user_name(self) -> str:
        return str(self.user.get("Name") or "")

    def authorization_header(self) -> str:
        parts = [
            f'Client="{CLIENT_NAME}"',
            f'Device="{DEVICE_NAME}"',
            f'DeviceId="{self.device_id}"',
            f'Version="{CLIENT_VERSION}"',
        ]
        if self.token:
            parts.append(f'Token="{self.token}"')
        return "MediaBrowser " + ", ".join(parts)

    def login(self, username: str, password: str) -> dict:
        data = self._request(
            "POST",
            "/Users/AuthenticateByName",
            json={"Username": username, "Pw": password},
        )
        self.token = data.get("AccessToken", "")
        self.user = data.get("User", {}) or {}
        if not self.token:
            raise EmbyError("登录失败：服务器未返回访问令牌")
        get_logger("api").info(
            "登录成功：%s（%s）", self.user.get("Name", "—"), self.server
        )
        return self.user

    def logout(self) -> None:
        try:
            self._request("POST", "/Sessions/Logout")
        except EmbyError:
            pass
        get_logger("api").info("注销会话：%s", self.user.get("Name", "—"))
        self.token = ""
        self.user = {}

    def server_info(self) -> dict:
        return self._request("GET", "/System/Info")

    def get_user(self, timeout: Optional[tuple] = None) -> dict:
        return self._request(
            "GET",
            f"/Users/{self.user_id}",
            timeout=timeout or (5.0, 10.0),
        )

    # ---- 通用请求 -------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Any = None,
        timeout: Optional[tuple] = None,
        stream: bool = False,
        ok: Iterable[int] = (200,),
    ) -> Any:
        if not self.server:
            raise EmbyError("未配置服务器地址")
        url = self.server + path
        started = time.monotonic()
        headers = {
            "X-Emby-Authorization": self.authorization_header(),
            "Accept": "application/json",
        }
        if self.token:
            headers["X-Emby-Token"] = self.token
        idempotent = method == "GET" or path.endswith("/AuthenticateByName")
        attempts = 3 if idempotent else 1
        proxies = self.proxy_manager.proxies_for(url)
        last_error: Optional[requests.RequestException] = None
        resp = None
        for attempt in range(attempts):
            try:
                resp = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=timeout or DEFAULT_TIMEOUT,
                    stream=stream,
                    proxies=proxies or None,
                )
                break
            except requests.RequestException as exc:
                last_error = exc
                if isinstance(exc, requests.exceptions.ProxyError):
                    # 代理可能刚被关闭/切换，立刻复查一次
                    self.proxy_manager.force_refresh()
                if attempt + 1 < attempts:
                    time.sleep(0.8 * (attempt + 1))
                else:
                    get_logger("api").warning(
                        "%s %s 失败：%s", method, path, exc
                    )
                    raise EmbyError(
                        _network_error_message(exc, url, self.proxy)
                    ) from exc
        if resp is None:
            raise EmbyError(_network_error_message(last_error, url, self.proxy))

        get_logger("api").debug(
            "%s %s -> %s (%.0fms)",
            method, path, resp.status_code, (time.monotonic() - started) * 1000,
        )
        if resp.status_code >= 400:
            raise EmbyError(_error_message(resp), resp.status_code)
        if stream:
            return resp
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    # ---- 媒体库 ---------------------------------------------------------
    def get_views(self) -> List[dict]:
        data = self._request("GET", f"/Users/{self.user_id}/Views")
        return data.get("Items", [])

    def get_latest(self, parent_id: str, limit: int = 12) -> List[dict]:
        data = self._request(
            "GET",
            f"/Users/{self.user_id}/Items/Latest",
            params={"ParentId": parent_id, "Limit": limit, "Fields": GRID_FIELDS},
        )
        return data if isinstance(data, list) else data.get("Items", [])

    def get_resume(self, limit: int = 12) -> List[dict]:
        data = self._request(
            "GET",
            f"/Users/{self.user_id}/Items/Resume",
            params={"Limit": limit, "Fields": GRID_FIELDS},
        )
        return data.get("Items", [])

    def get_items(
        self,
        *,
        parent_id: str = "",
        include_types: str = "",
        start: int = 0,
        limit: int = 60,
        sort_by: str = "SortName",
        sort_order: str = "Ascending",
        recursive: bool = True,
        search_term: str = "",
        genres: str = "",
        filters: str = "",
        fields: str = GRID_FIELDS,
    ) -> dict:
        params: Dict[str, Any] = {
            "Recursive": str(recursive).lower(),
            "StartIndex": start,
            "Limit": limit,
            "SortBy": sort_by,
            "SortOrder": sort_order,
            "Fields": fields,
            "ImageTypeLimit": 1,
            "EnableImageTypes": "Primary,Backdrop,Thumb",
        }
        if parent_id:
            params["ParentId"] = parent_id
        if include_types:
            params["IncludeItemTypes"] = include_types
        if search_term:
            params["SearchTerm"] = search_term
        if genres:
            params["Genres"] = genres
        if filters:
            params["Filters"] = filters
        return self._request("GET", f"/Users/{self.user_id}/Items", params=params)

    def get_item(self, item_id: str, fields: str = DETAIL_FIELDS) -> dict:
        return self._request(
            "GET",
            f"/Users/{self.user_id}/Items/{item_id}",
            params={"Fields": fields},
        )

    def get_genres(self, parent_id: str = "") -> List[dict]:
        params = {"UserId": self.user_id, "Limit": 200, "SortBy": "SortName"}
        if parent_id:
            params["ParentId"] = parent_id
        data = self._request("GET", "/Genres", params=params)
        return data.get("Items", [])

    def search(self, term: str, include_types: str = "Movie,Series,Episode,BoxSet,Video", limit: int = 80) -> List[dict]:
        data = self.get_items(
            include_types=include_types,
            search_term=term,
            limit=limit,
            sort_by="SortName",
            fields=GRID_FIELDS,
        )
        return data.get("Items", [])

    # ---- 剧集 -----------------------------------------------------------
    def get_seasons(self, series_id: str) -> List[dict]:
        data = self._request(
            "GET",
            f"/Shows/{series_id}/Seasons",
            params={"UserId": self.user_id, "Fields": "ImageTags,UserData,ChildCount"},
        )
        return data.get("Items", [])

    def get_episodes(self, series_id: str, season_id: str = "") -> List[dict]:
        params: Dict[str, Any] = {
            "UserId": self.user_id,
            "Fields": EPISODE_FIELDS,
            "ImageTypeLimit": 1,
            "EnableImageTypes": "Primary,Thumb,Backdrop",
        }
        if season_id:
            params["SeasonId"] = season_id
        data = self._request("GET", f"/Shows/{series_id}/Episodes", params=params)
        return data.get("Items", [])

    def get_similar(self, item_id: str, limit: int = 12) -> List[dict]:
        data = self._request(
            "GET",
            f"/Items/{item_id}/Similar",
            params={"UserId": self.user_id, "Limit": limit, "Fields": GRID_FIELDS},
        )
        return data.get("Items", [])

    # ---- 用户数据 -------------------------------------------------------
    def set_favorite(self, item_id: str, favorite: bool) -> None:
        method = "POST" if favorite else "DELETE"
        self._request(method, f"/Users/{self.user_id}/FavoriteItems/{item_id}")

    def set_played(self, item_id: str, played: bool) -> None:
        method = "POST" if played else "DELETE"
        self._request(method, f"/Users/{self.user_id}/PlayedItems/{item_id}")

    # ---- 播放 -----------------------------------------------------------
    def device_profile(self) -> dict:
        video_codecs = (
            "h264,hevc,av1,vp8,vp9,mpeg1video,mpeg2video,mpeg4,"
            "msmpeg4v2,msmpeg4v3,vc1,wmv3,theora"
        )
        audio_codecs = (
            "aac,mp3,mp2,ac3,eac3,dts,dtshd,truehd,flac,opus,vorbis,"
            "pcm_s16le,pcm_s24le,wma,wmapro"
        )
        return {
            "MaxStreamingBitrate": 200_000_000,
            "MaxStaticBitrate": 200_000_000,
            "MusicStreamingTranscodingBitrate": 384_000,
            "DirectPlayProfiles": [
                {
                    "Container": "mkv,webm,mp4,m4v,mov,avi,ts,m2ts,mpeg,mpg,wmv,flv,ogv,3gp",
                    "Type": "Video",
                    "VideoCodec": video_codecs,
                    "AudioCodec": audio_codecs,
                },
                {
                    "Container": "mp3,flac,aac,m4a,ogg,opus,wav,wma",
                    "Type": "Audio",
                    "AudioCodec": audio_codecs,
                },
            ],
            "TranscodingProfiles": [],
            "ContainerProfiles": [],
            "CodecProfiles": [],
            "SubtitleProfiles": [
                {"Format": "srt", "Method": "External"},
                {"Format": "subrip", "Method": "External"},
                {"Format": "ass", "Method": "External"},
                {"Format": "ssa", "Method": "External"},
                {"Format": "vtt", "Method": "External"},
                {"Format": "pgssub", "Method": "Embed"},
                {"Format": "dvdsub", "Method": "Embed"},
            ],
        }

    def playback_info(self, item_id: str, media_source_id: str = "") -> dict:
        body = {
            "UserId": self.user_id,
            "StartTimeTicks": 0,
            "IsPlayback": True,
            "AutoOpenLiveStream": True,
            "MaxStreamingBitrate": 200_000_000,
            "DeviceProfile": self.device_profile(),
        }
        if media_source_id:
            body["MediaSourceId"] = media_source_id
        return self._request(
            "POST",
            f"/Items/{item_id}/PlaybackInfo",
            params={"UserId": self.user_id},
            json=body,
        )

    def _report(self, path: str, body: dict) -> None:
        self._request("POST", path, json=body)

    def report_start(
        self,
        item_id: str,
        media_source_id: str,
        play_session_id: str,
        position_ticks: int,
        play_method: str = "DirectPlay",
    ) -> None:
        self._report(
            "/Sessions/Playing",
            {
                "ItemId": item_id,
                "MediaSourceId": media_source_id,
                "PlaySessionId": play_session_id,
                "PositionTicks": int(position_ticks),
                "CanSeek": True,
                "IsPaused": False,
                "IsMuted": False,
                "PlayMethod": play_method,
                "RepeatMode": "RepeatNone",
                "PlaylistIndex": 0,
                "PlaylistLength": 1,
            },
        )

    def report_progress(
        self,
        item_id: str,
        media_source_id: str,
        play_session_id: str,
        position_ticks: int,
        paused: bool = False,
        volume: int = 100,
        play_method: str = "DirectPlay",
    ) -> None:
        self._report(
            "/Sessions/Playing/Progress",
            {
                "ItemId": item_id,
                "MediaSourceId": media_source_id,
                "PlaySessionId": play_session_id,
                "PositionTicks": int(position_ticks),
                "CanSeek": True,
                "IsPaused": bool(paused),
                "IsMuted": volume <= 0,
                "VolumeLevel": int(volume),
                "PlayMethod": play_method,
                "EventName": "TimeUpdate",
            },
        )

    def report_stop(
        self,
        item_id: str,
        media_source_id: str,
        play_session_id: str,
        position_ticks: int,
        play_method: str = "DirectPlay",
    ) -> None:
        self._report(
            "/Sessions/Playing/Stopped",
            {
                "ItemId": item_id,
                "MediaSourceId": media_source_id,
                "PlaySessionId": play_session_id,
                "PositionTicks": int(position_ticks),
                "PlayMethod": play_method,
            },
        )

    # ---- 地址辅助 -------------------------------------------------------
    def image(
        self,
        item_id: str,
        kind: str = "Primary",
        *,
        index: Optional[int] = None,
        tag: Optional[str] = None,
        max_width: Optional[int] = None,
    ) -> str:
        return image_url(
            self.server,
            item_id,
            kind,
            index=index,
            tag=tag,
            max_width=max_width,
        )

    def item_image(self, item: dict, kind: str = "Primary", max_width: Optional[int] = None) -> str:
        item_id = str(item.get("Id", ""))
        tags = item.get("ImageTags") or {}
        tag = tags.get(kind)
        if kind == "Backdrop":
            backdrops = item.get("BackdropImageTags") or []
            if not backdrops:
                return ""
            return self.image(item_id, "Backdrop", index=0, tag=backdrops[0], max_width=max_width)
        if not tag:
            return ""
        return self.image(item_id, kind, tag=tag, max_width=max_width)

    def stream_path(self, item_id: str, media_source_id: str, play_session_id: str = "") -> str:
        params = {"static": "true", "MediaSourceId": media_source_id}
        if play_session_id:
            params["PlaySessionId"] = play_session_id
        return f"/Videos/{item_id}/stream?" + urlencode(params)

    def subtitle_path(self, item_id: str, media_source_id: str, index: int, fmt: str = "srt") -> str:
        fmt = (fmt or "srt").lower()
        if fmt == "subrip":
            fmt = "srt"
        if fmt == "pgssub":
            fmt = "sup"
        return f"/Videos/{item_id}/{media_source_id}/Subtitles/{index}/Stream.{fmt}"


def _network_error_message(
    exc: Optional[requests.RequestException],
    url: str,
    proxy: Optional[ProxyConfig],
) -> str:
    host = urlsplit(url).hostname or url
    text = str(exc or "")
    lowered = text.lower()
    if isinstance(exc, requests.exceptions.ProxyError) or "proxy" in lowered:
        target = proxy.url if proxy else "系统代理"
        return f"代理连接失败（{target}），请检查系统代理设置后重试"
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return f"连接服务器超时：{host}。请检查网络或代理设置"
    if isinstance(exc, requests.exceptions.SSLError):
        return f"TLS 连接失败：{host}。请检查网络、系统代理或证书"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"无法连接服务器：{host}。请检查网络或代理设置"
    return f"网络错误：{text or '连接失败'}"


def _error_message(resp: requests.Response) -> str:
    """从响应里提炼可读的错误信息。"""
    text = ""
    try:
        text = (resp.text or "").strip()
    except Exception:  # noqa: BLE001 - 读取失败时退化为状态码描述
        text = ""
    if text.startswith("{"):
        try:
            data = resp.json()
            text = str(data.get("message") or data.get("Message") or text)
        except ValueError:
            pass
    text = re.sub(r"\s+", " ", text)[:300]
    status = resp.status_code
    if status == 401:
        return "认证失败：用户名或密码错误，或登录已过期"
    if status == 403:
        if "允许的客户端" in text:
            return text or "服务器拒绝了该客户端的访问"
        return text or "没有访问权限（403）"
    if status in (502, 503, 504):
        return "服务器暂时不可用（可能是网络或系统代理异常），请稍后重试"
    if status == 404:
        return "请求的资源不存在（404）"
    return text or f"请求失败（HTTP {status}）"


def person_image_url(server: str, person_id: str, max_width: int = 200) -> str:
    return image_url(server, person_id, "Primary", max_width=max_width)


def parse_runtime(ticks: Optional[int]) -> str:
    if not ticks:
        return ""
    minutes = int(ticks) // (TICKS * 60)
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {mins} 分"
    return f"{mins} 分钟"


def format_ticks(ticks: Optional[int]) -> str:
    total = int(ticks or 0) // TICKS
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
