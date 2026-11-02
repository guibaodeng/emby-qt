"""本地流媒体代理。

服务器在 Cloudflare 层按客户端名做白名单校验，只接受带
``X-Emby-Authorization`` 头的请求。播放器（libVLC）无法自定义该头，
因此这里在 127.0.0.1 上开一个极小的反向代理：它转发 Range 请求，
并注入认证头与 UA，VLC 只需要播放本地 URL。
"""

from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

from . import CLIENT_NAME
from .api import EmbyClient
from .logging_setup import get_logger

CHUNK = 128 * 1024


class StreamProxy:
    def __init__(self, client: EmbyClient) -> None:
        self.client = client
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port = 0
        self._progress_lock = threading.Lock()
        self._progress = {}

    # ---- 生命周期 -------------------------------------------------------
    def start(self) -> None:
        if self._httpd is not None:
            return
        proxy = self

        class Handler(_ProxyHandler):
            proxy_ref = proxy

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._httpd.allow_reuse_address = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="embyqt-stream-proxy",
            daemon=True,
        )
        self._thread.start()
        get_logger("stream").info("本机流代理已启动：127.0.0.1:%s", self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            finally:
                self._httpd = None
                self._thread = None
                get_logger("stream").info("本机流代理已停止")

    @property
    def running(self) -> bool:
        return self._httpd is not None

    # ---- URL 构造 -------------------------------------------------------
    # ---- 网速 / 缓冲统计 ----------------------------------------------
    def begin_playback(self, item_id: str, total: int = 0) -> None:
        """新播放会话：清空网速和缓冲窗口。"""
        with self._progress_lock:
            self._progress[str(item_id)] = {
                "total": max(0, int(total or 0)),
                "downloaded": 0,
                "windows": {},
                "seq": 0,
                "current": None,
            }

    def begin_request(self, item_id: str, start: int) -> Optional[int]:
        """记录一个新的 Range 请求窗口，返回窗口 key。"""
        with self._progress_lock:
            key = str(item_id)
            entry = self._progress.setdefault(
                key,
                {"total": 0, "downloaded": 0, "windows": {}, "seq": 0, "current": None},
            )
            entry.setdefault("windows", {})
            entry["seq"] = int(entry.get("seq", 0)) + 1
            window_key = entry["seq"]
            entry["windows"][window_key] = {
                "start": max(0, int(start)),
                "sent": 0,
            }
            entry["current"] = window_key
            # 保留最近的窗口，避免长播放无限增长；末尾探测不会覆盖数据窗口
            if len(entry["windows"]) > 8:
                for old in sorted(entry["windows"])[:-8]:
                    entry["windows"].pop(old, None)
            return window_key

    def add_progress(
        self, item_id: str, sent: int, window_key: Optional[int] = None
    ) -> None:
        with self._progress_lock:
            key = str(item_id)
            entry = self._progress.setdefault(
                key,
                {"total": 0, "downloaded": 0, "windows": {}, "seq": 0, "current": None},
            )
            count = int(sent)
            entry["downloaded"] = int(entry.get("downloaded", 0)) + count
            if window_key is not None:
                window = (entry.get("windows") or {}).get(window_key)
                if window is not None:
                    window["sent"] = int(window.get("sent", 0)) + count

    def set_progress_total(self, item_id: str, total: int) -> None:
        with self._progress_lock:
            entry = self._progress.setdefault(
                str(item_id),
                {"total": 0, "downloaded": 0, "windows": {}, "seq": 0, "current": None},
            )
            if total > 0:
                entry["total"] = max(int(entry.get("total", 0)), int(total))

    def bytes_for(self, item_id: str) -> int:
        """本次播放累计下载字节（用于实时网速）。"""
        with self._progress_lock:
            entry = self._progress.get(str(item_id))
            if not entry:
                return 0
            return int(entry.get("downloaded", 0))

    def windows_for(self, item_id: str) -> list:
        """当前已缓冲的区间列表，元素为 (起点%, 终点%)。"""
        with self._progress_lock:
            entry = self._progress.get(str(item_id))
            if not entry or int(entry.get("total", 0)) <= 0:
                return []
            total = float(entry["total"])
            raw = []
            for window in (entry.get("windows") or {}).values():
                sent = int(window.get("sent", 0))
                if sent <= 0:
                    continue
                start = max(0.0, min(100.0, int(window.get("start", 0)) * 100.0 / total))
                end = max(0.0, min(100.0, (int(window.get("start", 0)) + sent) * 100.0 / total))
                if end > start:
                    raw.append((start, end))
            raw.sort()
            merged = []
            for start, end in raw:
                if merged and start <= merged[-1][1] + 0.02:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                else:
                    merged.append((start, end))
            return merged

    def begin_seek(self, item_id: str, percent: float) -> bool:
        """跳转后处理缓冲窗口。

        目标已在缓冲区间内时保留窗口并返回 True；
        目标未缓冲时清空窗口并返回 False，后续新的 Range 请求会从目标位置重新统计。
        """
        with self._progress_lock:
            entry = self._progress.get(str(item_id))
            if not entry:
                return False
            if int(entry.get("total", 0)) <= 0:
                entry["windows"] = {}
                entry["current"] = None
                return False
            total = int(entry["total"])
            target = total * max(0.0, min(100.0, float(percent))) / 100.0
            slack = min(int(total * 0.005), 8 * 1024 * 1024)
            for window in (entry.get("windows") or {}).values():
                start = int(window.get("start", 0))
                end = start + int(window.get("sent", 0))
                if start - slack <= target <= end + slack:
                    return True
            entry["windows"] = {}
            entry["current"] = None
            return False

    def media_url(self, item_id: str, media_source_id: str, play_session_id: str = "") -> str:
        params = f"src={_q(media_source_id)}"
        if play_session_id:
            params += f"&psid={_q(play_session_id)}"
        return f"http://127.0.0.1:{self.port}/media/{_q(item_id)}?{params}"

    def subtitle_url(self, item_id: str, media_source_id: str, index: int, fmt: str = "srt") -> str:
        path = self.client.subtitle_path(item_id, media_source_id, index, fmt)
        return f"http://127.0.0.1:{self.port}/sub?p={_q(path)}"


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    proxy_ref: StreamProxy  # 由子类注入

    def log_message(self, fmt: str, *args) -> None:  # 静默
        pass

    def _log(self, *parts) -> None:
        get_logger("stream").debug(" ".join(str(part) for part in parts))

    # ---- HTTP 方法 ------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._handle(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(head_only=True)

    # ---- 实现 -----------------------------------------------------------
    def _upstream(self) -> Optional[str]:
        parsed = urlparse(self.path)
        client = self.proxy_ref.client
        if parsed.path.startswith("/media/"):
            item_id = parsed.path.rsplit("/", 1)[-1]
            query = parse_qs(parsed.query)
            src = (query.get("src") or [""])[0]
            psid = (query.get("psid") or [""])[0]
            if not item_id or not src:
                return None
            return client.server + client.stream_path(item_id, src, psid)
        if parsed.path == "/sub":
            query = parse_qs(parsed.query)
            path = (query.get("p") or [""])[0]
            if not path.startswith("/Videos/"):
                return None
            return client.server + path
        return None

    def _handle(self, *, head_only: bool) -> None:
        parsed = urlparse(self.path)
        item_id = parsed.path.rsplit("/", 1)[-1] if parsed.path.startswith("/media/") else ""
        range_header = self.headers.get("Range")
        range_start = 0
        if range_header:
            try:
                range_start = int(range_header.split("=", 1)[1].split("-", 1)[0] or 0)
            except (IndexError, ValueError):
                range_start = 0
        upstream = self._upstream()
        if not upstream:
            self._fail(404, "bad proxy request")
            return
        if "sent" not in dir():
            sent = 0
        client = self.proxy_ref.client
        headers = {
            "X-Emby-Authorization": client.authorization_header(),
            "User-Agent": CLIENT_NAME,
            "Accept-Encoding": "identity",
        }
        if range_header:
            headers["Range"] = range_header

        self._log("REQ", self.command, self.path, "range=", range_header)
        proxies = client.proxy_manager.proxies_for(upstream)
        try:
            resp = requests.get(
                upstream,
                headers=headers,
                stream=True,
                timeout=(10, 60),
                allow_redirects=True,
                proxies=proxies or None,
            )
        except requests.RequestException as exc:
            self._log("UPSTREAM-ERROR", exc)
            get_logger("stream").warning("上游请求失败：%s", exc)
            self._fail(502, f"upstream error: {exc}")
            return

        try:
            if resp.status_code >= 400:
                get_logger("stream").warning(
                    "上游返回 %s：%s", resp.status_code, resp.text[:120]
                )
                self._fail(resp.status_code, resp.text[:200])
                return
            window_key = None
            if item_id and not head_only:
                window_key = self.proxy_ref.begin_request(item_id, range_start)
            self.send_response(resp.status_code)
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
            self.send_header("Content-Type", ctype)
            length = resp.headers.get("Content-Length")
            if length:
                self.send_header("Content-Length", length)
            else:
                self.send_header("Connection", "close")
                self.close_connection = True
            content_range = resp.headers.get("Content-Range")
            if content_range:
                self.send_header("Content-Range", content_range)
            if item_id:
                total = 0
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        total = int(content_range.rsplit("/", 1)[1])
                    except ValueError:
                        total = 0
                if not total and length:
                    try:
                        total = int(length)
                    except ValueError:
                        total = 0
                get_logger("stream").debug(
                    "媒体响应 item=%s status=%s length=%s content-range=%s total=%s",
                    item_id, resp.status_code, length,
                    resp.headers.get("Content-Range"), total,
                )
                if total:
                    self.proxy_ref.set_progress_total(item_id, total)
            self.send_header("Accept-Ranges", resp.headers.get("Accept-Ranges", "bytes"))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._log("RESP", resp.status_code, "len=", length, "cr=", content_range)

            if head_only:
                return
            sent = 0
            for chunk in resp.iter_content(CHUNK):
                if not chunk:
                    continue
                self.wfile.write(chunk)
                self.wfile.flush()
                sent += len(chunk)
                if item_id:
                    self.proxy_ref.add_progress(item_id, len(chunk), window_key)
        except (BrokenPipeError, ConnectionResetError) as exc:
            self._log("CLIENT-CLOSE", exc, "sent=", sent)
            self.close_connection = True
        except requests.RequestException as exc:
            self._log("STREAM-ERROR", exc, "sent=", sent)
            self.close_connection = True
        finally:
            self._log("DONE", "sent=", sent)
            resp.close()

    def _fail(self, status: int, message: str) -> None:
        body = str(message).encode("utf-8", "replace")[:500]
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True
