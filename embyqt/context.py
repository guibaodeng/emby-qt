"""应用上下文：集中持有客户端、流代理、图片加载器与配置。"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QSize

from .api import EmbyClient
from .config import Config
from .imagecache import ImageStore
from .net import ProxyConfig, ProxyManager, default_manager
from .streamproxy import StreamProxy


class AppContext:
    def __init__(
        self,
        config: Config,
        client: EmbyClient,
        proxy: StreamProxy,
        proxy_manager: Optional[ProxyManager] = None,
        net_proxy: Optional[ProxyConfig] = None,
    ) -> None:
        self.config = config
        self.client = client
        self.proxy = proxy
        self.proxy_manager = proxy_manager or client.proxy_manager
        if net_proxy is not None:
            self.proxy_manager = ProxyManager(static_config=net_proxy)
        self.images = ImageStore(proxy_manager=self.proxy_manager)

    @property
    def net_proxy(self) -> Optional[ProxyConfig]:
        """当前代理（动态复查）。"""
        return self.proxy_manager.current()

    # ---- 图片地址 -------------------------------------------------------
    def poster_url(self, item: dict) -> str:
        url = self.client.item_image(item, "Primary", max_width=320)
        if not url:
            series_id = item.get("SeriesId")
            tag = item.get("SeriesPrimaryImageTag")
            if series_id and tag:
                url = self.client.image(series_id, "Primary", tag=tag, max_width=320)
        return url

    def thumb_url(self, item: dict, width: int = 480) -> str:
        url = self.client.item_image(item, "Primary", max_width=width)
        if not url:
            series_id = item.get("SeriesId")
            tag = item.get("SeriesPrimaryImageTag")
            if series_id and tag:
                url = self.client.image(series_id, "Primary", tag=tag, max_width=width)
        return url

    def backdrop_url(self, item: dict, width: int = 1400) -> str:
        url = self.client.item_image(item, "Backdrop", max_width=width)
        if url:
            return url
        return self.poster_url(item)

    def person_url(self, person_id: str, width: int = 180) -> str:
        return self.client.image(person_id, "Primary", max_width=width)

    # ---- 图片加载 -------------------------------------------------------
    def load_image(
        self,
        url: str,
        size: QSize,
        callback: Callable,
        radius: int = 0,
        crop: bool = True,
    ) -> None:
        self.images.load(url, size, callback, radius=radius, crop=crop)

    # ---- 便捷判断 -------------------------------------------------------
    @property
    def user(self) -> dict:
        return self.client.user

    def is_played(self, item: dict) -> bool:
        return bool((item.get("UserData") or {}).get("Played"))

    def resume_ticks(self, item: dict) -> int:
        return int((item.get("UserData") or {}).get("PlaybackPositionTicks") or 0)

    def progress_fraction(self, item: dict) -> float:
        ticks = self.resume_ticks(item)
        runtime = int(item.get("RunTimeTicks") or 0)
        if not ticks or not runtime:
            return 0.0
        return max(0.0, min(1.0, ticks / runtime))
