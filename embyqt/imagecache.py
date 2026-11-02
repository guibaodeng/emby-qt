"""异步图片加载：内存 LRU + QNetworkDiskCache 磁盘缓存。"""

from __future__ import annotations

import os
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QRectF, QSize, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkProxy,
    QNetworkProxyFactory,
    QNetworkProxyQuery,
    QNetworkRequest,
)

from . import CLIENT_NAME
from .net import ProxyConfig, ProxyManager, default_manager

_MEM_LIMIT = 400


def rounded_pixmap(source: QPixmap, size: QSize, radius: int = 0, crop: bool = True) -> QPixmap:
    """按目标尺寸缩放（可选裁剪填充）并绘制圆角。"""
    if source.isNull():
        return QPixmap()
    target = QPixmap(size)
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    if crop:
        # 等比放大后居中裁剪，目标区域始终铺满整块画布
        scaled = source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - size.width()) // 2
        y = (scaled.height() - size.height()) // 2
        source_rect = QRectF(x, y, size.width(), size.height())
        target_rect = QRectF(0, 0, size.width(), size.height())
    else:
        # 等比缩放并居中留白
        scaled = source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (size.width() - scaled.width()) // 2
        y = (size.height() - scaled.height()) // 2
        source_rect = QRectF(0, 0, scaled.width(), scaled.height())
        target_rect = QRectF(x, y, scaled.width(), scaled.height())

    if radius > 0:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
        painter.setClipPath(path)
    painter.drawPixmap(target_rect, scaled, source_rect)
    painter.end()
    return target


def placeholder(size: QSize, radius: int, seed: str = "") -> QPixmap:
    """无图时的占位图：暗色渐变 + 首字母。"""
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
    painter.setClipPath(path)
    painter.fillPath(path, QColor("#20242f"))
    painter.setPen(QColor("#3a4152"))
    font = painter.font()
    font.setPointSize(8)
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
    painter.setFont(font)
    painter.drawText(
        QRectF(0, 0, size.width(), size.height()),
        Qt.AlignmentFlag.AlignCenter,
        "EMBY",
    )
    painter.end()
    return pm


class _DynamicProxyFactory(QNetworkProxyFactory):
    """Qt 侧按请求动态返回代理，跟随 ProxyManager 的实时状态。"""

    def __init__(self, manager: ProxyManager) -> None:
        super().__init__()
        self._manager = manager

    def queryProxy(self, query: QNetworkProxyQuery = QNetworkProxyQuery()) -> list:  # noqa: N802
        config = self._manager.current()
        if config is not None and config.enabled:
            host = ""
            try:
                host = query.peerHostName()
            except Exception:  # noqa: BLE001
                host = ""
            if host and config.bypass_for(host):
                return [QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)]
            proxy_type = (
                QNetworkProxy.ProxyType.Socks5Proxy
                if config.scheme.startswith("socks")
                else QNetworkProxy.ProxyType.HttpProxy
            )
            return [QNetworkProxy(proxy_type, config.host, config.port)]
        return [QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)]


class ImageStore(QObject):
    """全局图片加载器，所有 UI 共用。"""

    def __init__(
        self,
        parent: Optional[QObject] = None,
        proxy: Optional[ProxyConfig] = None,
        proxy_manager: Optional[ProxyManager] = None,
    ) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._nam.setTransferTimeout(20000)
        if proxy_manager is None:
            proxy_manager = (
                ProxyManager(static_config=proxy) if proxy is not None else default_manager()
            )
        self._proxy_factory = _DynamicProxyFactory(proxy_manager)
        self._nam.setProxyFactory(self._proxy_factory)
        cache_dir = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.CacheLocation
            )
        ) / "images"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            cache_dir = Path(tempfile.mkdtemp(prefix="embyqt-images-"))
        cache = QNetworkDiskCache(self)
        cache.setCacheDirectory(str(cache_dir))
        cache.setMaximumCacheSize(512 * 1024 * 1024)
        self._nam.setCache(cache)
        self._memory: "OrderedDict[Tuple[str, int, int, int], QPixmap]" = OrderedDict()
        self._pending: Dict[Tuple[str, int, int, int], list] = {}
        self._retried: set = set()

    # ---- 对外接口 -------------------------------------------------------
    def load(
        self,
        url: str,
        size: QSize,
        callback: Callable[[QPixmap], None],
        radius: int = 0,
        crop: bool = True,
    ) -> None:
        if not url:
            callback(placeholder(size, radius))
            return
        key = (url, size.width(), size.height(), radius)
        cached = self._memory.get(key)
        if cached is not None:
            self._memory.move_to_end(key)
            callback(cached)
            return
        if key in self._pending:
            self._pending[key].append(callback)
            return
        self._pending[key] = [callback]
        self._start_request(key, url, size, radius, crop)

    def _start_request(self, key, url: str, size: QSize, radius: int, crop: bool) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.PreferCache,
        )
        request.setRawHeader(b"User-Agent", CLIENT_NAME.encode())
        request.setRawHeader(b"Accept", b"image/*")
        reply = self._nam.get(request)
        reply.finished.connect(lambda: self._on_finished(key, size, radius, crop, reply))

    def clear_memory(self) -> None:
        self._memory.clear()

    def clear_disk(self) -> None:
        cache = self._nam.cache()
        if cache is not None:
            cache.clear()

    # ---- 内部 -----------------------------------------------------------
    def _on_finished(self, key, size: QSize, radius: int, crop: bool, reply) -> None:
        callbacks = self._pending.pop(key, [])
        pixmap = QPixmap()
        if reply.error() == reply.NetworkError.NoError:
            pixmap.loadFromData(reply.readAll())
        if os.environ.get("EMBYQT_DEBUG_IMAGES"):
            print(
                "[image]",
                reply.url().toString()[-70:],
                "status=",
                reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute),
                "error=",
                reply.error(),
                "bytes=",
                pixmap.width(),
                "x",
                pixmap.height(),
                file=sys.stderr,
                flush=True,
            )
        reply.deleteLater()

        if pixmap.isNull() and reply.error() != reply.NetworkError.NoError and key not in self._retried:
            # 网络抖动导致失败时重试一次，避免整墙占位图
            self._retried.add(key)
            self._pending[key] = callbacks
            self._start_request(key, reply.url().toString(), size, radius, crop)
            reply.deleteLater()
            return

        if pixmap.isNull():
            result = placeholder(size, radius)
        else:
            result = rounded_pixmap(pixmap, size, radius, crop)
            self._memory[key] = result
            while len(self._memory) > _MEM_LIMIT:
                self._memory.popitem(last=False)
        for callback in callbacks:
            try:
                callback(result)
            except RuntimeError:
                # 目标控件已被销毁
                continue
