"""跨平台系统代理探测与动态管理。

设计要点：
- 探测来源（按优先级）：
  1. ``EMBYQT_PROXY`` 显式覆盖（``none`` 表示强制直连）；
  2. ``urllib.request.getproxies()``：跨平台标准入口，
     Linux 读环境变量，Windows 读注册表，macOS 读 SystemConfiguration；
  3. macOS 补充：``scutil --proxy`` 解析手动代理和 PAC；
  4. Linux 桌面补充：GNOME gsettings（手动 / PAC）、KDE kioslaverc。
- ``ProxyManager`` 带 TTL 缓存，**每次网络请求前**调用 ``current()`` 复查，
  用户中途开关系统代理也能在数秒内生效，而不是只在启动时判断一次。
"""

from __future__ import annotations

import configparser
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlsplit
from urllib.request import getproxies


@dataclass
class ProxyConfig:
    url: str = ""
    host: str = ""
    port: int = 0
    scheme: str = "http"
    source: str = ""
    bypass: tuple = field(default_factory=tuple)

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.port)

    def describe(self) -> str:
        return f"{self.url}（{self.source}）" if self.enabled else "未使用代理"

    def signature(self) -> str:
        return f"{self.url}|{','.join(self.bypass)}"

    def bypass_for(self, host: str) -> bool:
        host = (host or "").lower()
        for pattern in self.bypass:
            pattern = pattern.strip().lower()
            if not pattern or pattern == "*":
                continue
            if "/" in pattern:
                try:
                    if ipaddress.ip_address(host) in ipaddress.ip_network(pattern, strict=False):
                        return True
                except ValueError:
                    pass
                continue
            if pattern.startswith("*."):
                pattern = pattern[2:]
            elif pattern.startswith("."):
                pattern = pattern[1:]
            if host == pattern or host.endswith("." + pattern):
                return True
        return False

    def proxies_for(self, url: str) -> Dict[str, str]:
        if not self.enabled:
            return {}
        host = urlsplit(url).hostname or ""
        if host and self.bypass_for(host):
            return {}
        return {"http": self.url, "https": self.url}


def _parse_proxy(value: str, source: str, bypass: tuple = ()) -> Optional[ProxyConfig]:
    value = (value or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    host = parts.hostname or ""
    port = parts.port or (1080 if parts.scheme.startswith("socks") else 8080)
    if not host:
        return None
    scheme = (parts.scheme or "http").lower()
    return ProxyConfig(
        url=f"{scheme}://{host}:{port}",
        host=host,
        port=int(port),
        scheme=scheme,
        source=source,
        bypass=tuple(bypass),
    )


# ---------------------------------------------------------------------------
# 各平台探测
# ---------------------------------------------------------------------------
def _normalize_bypass(value) -> tuple:
    if isinstance(value, (tuple, list)):
        parts = value
    else:
        parts = str(value or "").split(",")
    return tuple(str(part).strip().strip("'").strip('"') for part in parts if str(part).strip())


def _urllib_proxy() -> Optional[ProxyConfig]:
    """跨平台标准入口：Linux env / Windows 注册表 / macOS 系统配置。"""
    try:
        proxies = getproxies()
    except Exception:  # noqa: BLE001 - 系统接口失败时退回直连
        return None
    if not proxies:
        return None
    chosen = (
        proxies.get("https")
        or proxies.get("http")
        or proxies.get("all")
        or proxies.get("socks")
        or ""
    )
    if not chosen:
        return None
    source = "环境变量" if (os.environ.get("https_proxy") or os.environ.get("http_proxy")) else "系统代理"
    return _parse_proxy(chosen, source, _normalize_bypass(proxies.get("no")))


def _gsettings_get(schema: str, key: str) -> str:
    for _ in range(2):
        try:
            result = subprocess.run(
                ["gsettings", "get", schema, key],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        value = result.stdout.strip().strip("'").strip('"')
        if value:
            return value
        time.sleep(0.05)
    return ""


def _pac_proxy(url: str, source: str = "PAC") -> Optional[ProxyConfig]:
    """从 PAC 里提取默认 PROXY/HTTPS 条目（复杂规则按第一条兜底）。"""
    if not url:
        return None
    try:
        if url.startswith("file://"):
            with open(url[7:], "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
        elif url.startswith("http://") or url.startswith("https://"):
            import requests

            session = requests.Session()
            session.trust_env = False
            text = session.get(url, timeout=1.5).text
        else:
            return None
    except Exception:  # noqa: BLE001 - PAC 不可用时退回直连
        return None
    match = re.search(r"(?:PROXY|HTTPS)\s+([^\s;]+)", text, re.IGNORECASE)
    return _parse_proxy(match.group(1), source) if match else None


def _gnome_proxy() -> Optional[ProxyConfig]:
    if not shutil.which("gsettings"):
        return None
    root = "org.gnome.system.proxy"
    mode = ""
    for _ in range(3):
        mode = _gsettings_get(root, "mode")
        if mode in ("manual", "auto"):
            break
        time.sleep(0.08)
    if mode not in ("manual", "auto"):
        # 有些环境下 mode 会偶发读成 none，但 PAC 仍配置着；兜底再试一次 PAC
        pac = _pac_proxy(_gsettings_get(root, "autoconfig-url"), "GNOME PAC")
        if pac is not None:
            pac.bypass = _normalize_bypass(_gsettings_get(root, "ignore-hosts").strip("[]"))
            return pac
        return None
    bypass = _normalize_bypass(_gsettings_get(root, "ignore-hosts").strip("[]"))
    if mode == "auto":
        pac = _pac_proxy(_gsettings_get(root, "autoconfig-url"), "GNOME PAC")
        if pac is not None:
            pac.bypass = bypass
            return pac

    for schema in ("https", "http", "socks"):
        host = _gsettings_get(f"{root}.{schema}", "host")
        port = _gsettings_get(f"{root}.{schema}", "port")
        if host and port.isdigit() and int(port) > 0:
            scheme = "socks5" if schema == "socks" else "http"
            return ProxyConfig(
                url=f"{scheme}://{host}:{port}",
                host=host,
                port=int(port),
                scheme=scheme,
                source="GNOME 系统代理",
                bypass=bypass,
            )
    return None


def _kde_proxy() -> Optional[ProxyConfig]:
    path = os.path.expanduser("~/.config/kioslaverc")
    if not os.path.exists(path):
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    if not parser.has_section("Proxy Settings"):
        return None
    section = parser["Proxy Settings"]
    proxy_type = section.get("ProxyType", "0").strip()
    if proxy_type not in ("1", "2"):
        return None
    bypass = _normalize_bypass(section.get("NoProxyFor", ""))
    if proxy_type == "2":
        pac = _pac_proxy(section.get("Proxy Config Script", "").strip(), "KDE PAC")
        if pac is not None:
            pac.bypass = bypass
            return pac
        return None
    for key in ("httpsProxy", "httpProxy"):
        host = section.get(key, "").strip()
        port = section.get(f"{key}Port", "").strip()
        if host and port.isdigit():
            return ProxyConfig(
                url=f"http://{host}:{port}",
                host=host,
                port=int(port),
                scheme="http",
                source="KDE 系统代理",
                bypass=bypass,
            )
    return None


def _parse_scutil_proxy(text: str) -> Optional[ProxyConfig]:
    """解析 macOS ``scutil --proxy`` 的输出（PAC 优先，其次手动代理）。"""
    values = {}
    exceptions = []
    in_exceptions = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("ExceptionsList"):
            in_exceptions = True
            continue
        if in_exceptions:
            if line.startswith("}"):
                in_exceptions = False
                continue
            match = re.match(r"\d+\s*:\s*(.+)$", line)
            if match:
                exceptions.append(match.group(1).strip().strip('"'))
            continue
        match = re.match(r"([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip('"')

    bypass = tuple(exceptions)
    if values.get("ProxyAutoConfigEnable") == "1":
        pac_url = values.get("ProxyAutoConfigURLString", "")
        if pac_url:
            pac = _pac_proxy(pac_url, "macOS PAC")
            if pac is not None:
                pac.bypass = bypass
                return pac

    for kind in ("HTTPS", "HTTP", "SOCKS"):
        if values.get(f"{kind}Enable") != "1":
            continue
        host = values.get(f"{kind}Proxy", "")
        port = values.get(f"{kind}Port", "")
        if not host or not port.isdigit() or int(port) <= 0:
            continue
        scheme = "socks5" if kind == "SOCKS" else "http"
        return ProxyConfig(
            url=f"{scheme}://{host}:{int(port)}",
            host=host,
            port=int(port),
            scheme=scheme,
            source="macOS 系统代理",
            bypass=bypass,
        )
    return None


def _macos_proxy() -> Optional[ProxyConfig]:
    """读取 macOS 系统代理；PAC 也通过 scutil 获取。"""
    if sys.platform != "darwin":
        return None
    scutil = shutil.which("scutil") or "/usr/sbin/scutil"
    try:
        result = subprocess.run(
            [scutil, "--proxy"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _parse_scutil_proxy(result.stdout)


def detect_proxy() -> Optional[ProxyConfig]:
    """按优先级探测当前生效的系统代理，未配置则返回 None（直连）。"""
    override = os.environ.get("EMBYQT_PROXY", "").strip()
    if override:
        if override.lower() in ("none", "off", "direct"):
            return None
        return _parse_proxy(override, "EMBYQT_PROXY")

    config = _urllib_proxy()
    if config is not None:
        return config

    if sys.platform == "darwin":
        return _macos_proxy()
    if sys.platform.startswith("linux"):
        return _gnome_proxy() or _kde_proxy()
    return None


# ---------------------------------------------------------------------------
# 动态管理
# ---------------------------------------------------------------------------
class ProxyManager:
    """带 TTL 的代理状态，供每个请求前复查。

    - ``ttl``：缓存有效期（秒）。每次请求都会调用 ``current()``，
      超过 TTL 才重新探测，避免每个请求都去 spawn gsettings。
    - ``static_config``：显式指定的代理（测试/脚本用），永不刷新。
    """

    def __init__(self, ttl: float = 2.0, static_config: Optional[ProxyConfig] = None) -> None:
        self._ttl = max(0.0, float(ttl))
        self._static = static_config is not None
        self._config = static_config
        self._at = float("inf") if self._static else 0.0
        self._signature = ""
        self._lock = threading.RLock()

    def current(self) -> Optional[ProxyConfig]:
        if self._static:
            return self._config
        now = time.monotonic()
        if now - self._at < self._ttl:
            return self._config
        with self._lock:
            if time.monotonic() - self._at < self._ttl:
                return self._config
            self._refresh_locked()
            return self._config

    def force_refresh(self) -> Optional[ProxyConfig]:
        if self._static:
            return self._config
        with self._lock:
            self._refresh_locked()
            return self._config

    def _refresh_locked(self) -> None:
        config = detect_proxy()
        signature = config.signature() if config else "-"
        if self._signature and signature != self._signature:
            from .logging_setup import get_logger

            get_logger("net").info(
                "系统代理已变更：%s", config.describe() if config else "未使用代理"
            )
        self._signature = signature
        self._config = config
        self._at = time.monotonic()

    def proxies_for(self, url: str) -> Dict[str, str]:
        config = self.current()
        return config.proxies_for(url) if config else {}

    def describe(self) -> str:
        config = self.current()
        return config.describe() if config else "未使用代理"


_DEFAULT_MANAGER: Optional[ProxyManager] = None


def default_manager() -> ProxyManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = ProxyManager()
    return _DEFAULT_MANAGER
