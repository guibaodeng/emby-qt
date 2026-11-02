"""代理探测与网络错误提示的单元测试。"""

import os
import unittest
from unittest import mock

import requests

from embyqt import net
from embyqt.api import _network_error_message
from embyqt.net import ProxyConfig, _parse_proxy, detect_proxy


class ParseProxyTests(unittest.TestCase):
    def test_http_url(self):
        proxy = _parse_proxy("http://127.0.0.1:7897", "test")
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.host, "127.0.0.1")
        self.assertEqual(proxy.port, 7897)
        self.assertEqual(proxy.url, "http://127.0.0.1:7897")
        self.assertTrue(proxy.enabled)

    def test_host_port_without_scheme(self):
        proxy = _parse_proxy("127.0.0.1:1080", "test")
        self.assertEqual(proxy.url, "http://127.0.0.1:1080")

    def test_socks_scheme(self):
        proxy = _parse_proxy("socks5://127.0.0.1:1080", "test")
        self.assertEqual(proxy.scheme, "socks5")

    def test_empty(self):
        self.assertIsNone(_parse_proxy("", "test"))


class ProxyConfigTests(unittest.TestCase):
    def setUp(self):
        self.proxy = ProxyConfig(
            url="http://127.0.0.1:7897",
            host="127.0.0.1",
            port=7897,
            source="test",
            bypass=("localhost", "127.0.0.0/8", "internal.local"),
        )

    def test_proxies_for_remote(self):
        result = self.proxy.proxies_for("https://emby.example.com/Items")
        self.assertEqual(result["https"], "http://127.0.0.1:7897")

    def test_bypass_localhost(self):
        self.assertEqual(self.proxy.proxies_for("http://127.0.0.1:1234/x"), {})

    def test_bypass_domain_suffix(self):
        self.assertEqual(self.proxy.proxies_for("https://a.internal.local/x"), {})

    def test_describe(self):
        self.assertIn("127.0.0.1", self.proxy.describe())


class DetectProxyTests(unittest.TestCase):
    def test_force_none(self):
        with mock.patch.dict(os.environ, {"EMBYQT_PROXY": "none"}, clear=False):
            self.assertIsNone(detect_proxy())

    def test_force_url(self):
        with mock.patch.dict(os.environ, {"EMBYQT_PROXY": "http://10.0.0.1:8080"}, clear=False):
            proxy = detect_proxy()
            self.assertIsNotNone(proxy)
            self.assertEqual(proxy.source, "EMBYQT_PROXY")
            self.assertEqual(proxy.url, "http://10.0.0.1:8080")

    def test_env_proxy(self):
        env = {"EMBYQT_PROXY": "", "https_proxy": "http://10.0.0.2:3128"}
        with mock.patch.dict(os.environ, env, clear=False):
            proxy = detect_proxy()
            self.assertIsNotNone(proxy)
            self.assertIn("10.0.0.2", proxy.url)

    def test_empty_env_means_direct(self):
        env = {"EMBYQT_PROXY": "", "https_proxy": "", "http_proxy": "", "all_proxy": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(net, "_gnome_proxy", return_value=None):
                self.assertIsNone(detect_proxy())


class ScutilProxyTests(unittest.TestCase):
    def test_manual_proxy_with_exceptions(self):
        text = """
<dictionary> {
  ExceptionsList : <array> {
    0 : *.local
    1 : 192.168.0.0/16
  }
  HTTPEnable : 1
  HTTPPort : 7897
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7897
  HTTPSProxy : 127.0.0.1
  ProxyAutoConfigEnable : 0
}
"""
        proxy = net._parse_scutil_proxy(text)
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.url, "http://127.0.0.1:7897")
        self.assertEqual(proxy.source, "macOS 系统代理")
        self.assertIn("*.local", proxy.bypass)
        self.assertTrue(proxy.bypass_for("nas.local"))
        self.assertFalse(proxy.bypass_for("localhost"))

    def test_pac_proxy(self):
        text = """
<dictionary> {
  ExceptionsList : <array> {
    0 : internal.local
  }
  ProxyAutoConfigEnable : 1
  ProxyAutoConfigURLString : http://127.0.0.1:7890/proxy.pac
}
"""
        pac = ProxyConfig(
            url="http://127.0.0.1:7897", host="127.0.0.1", port=7897, source="macOS PAC"
        )
        with mock.patch.object(net, "_pac_proxy", return_value=pac) as fetch:
            proxy = net._parse_scutil_proxy(text)
        self.assertIs(proxy, pac)
        self.assertIn("internal.local", proxy.bypass)
        fetch.assert_called_once_with("http://127.0.0.1:7890/proxy.pac", "macOS PAC")

    def test_socks_proxy(self):
        text = """
<dictionary> {
  SOCKSEnable : 1
  SOCKSPort : 1080
  SOCKSProxy : 127.0.0.1
}
"""
        proxy = net._parse_scutil_proxy(text)
        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.scheme, "socks5")
        self.assertEqual(proxy.url, "socks5://127.0.0.1:1080")


class NetworkErrorMessageTests(unittest.TestCase):
    def test_proxy_error(self):
        message = _network_error_message(
            requests.exceptions.ProxyError("boom"),
            "https://host/x",
            ProxyConfig(url="http://127.0.0.1:7897", host="127.0.0.1", port=7897),
        )
        self.assertIn("代理连接失败", message)
        self.assertIn("127.0.0.1:7897", message)

    def test_timeout(self):
        message = _network_error_message(
            requests.exceptions.ConnectTimeout("boom"), "https://host/x", None
        )
        self.assertIn("超时", message)
        self.assertIn("host", message)

    def test_connection_error(self):
        message = _network_error_message(
            requests.exceptions.ConnectionError("refused"), "https://host/x", None
        )
        self.assertIn("无法连接服务器", message)


if __name__ == "__main__":
    unittest.main()


class ProxyManagerTests(unittest.TestCase):
    def test_static_config(self):
        config = _parse_proxy(
            "http://127.0.0.1:7897", "static", bypass=("127.0.0.0/8", "localhost")
        )
        manager = net.ProxyManager(static_config=config)
        self.assertIs(manager.current(), config)
        self.assertEqual(manager.proxies_for("https://host/x")["https"], config.url)
        self.assertEqual(manager.proxies_for("http://127.0.0.1:1/x"), {})

    def test_ttl_caches_detection(self):
        calls = []

        def fake_detect():
            calls.append(1)
            return _parse_proxy("http://10.0.0.1:8080", "fake")

        with mock.patch.object(net, "detect_proxy", side_effect=fake_detect):
            manager = net.ProxyManager(ttl=60)
            manager.current()
            manager.current()
            self.assertEqual(len(calls), 1)
            manager.force_refresh()
            self.assertEqual(len(calls), 2)

    def test_detects_mid_session_change(self):
        state = {"config": None}
        with mock.patch.object(net, "detect_proxy", side_effect=lambda: state["config"]):
            manager = net.ProxyManager(ttl=0)
            self.assertIsNone(manager.current())
            state["config"] = _parse_proxy("http://10.0.0.9:3128", "fake")
            self.assertIsNotNone(manager.current())
            self.assertEqual(
                manager.proxies_for("https://host/x")["https"],
                "http://10.0.0.9:3128",
            )


class RuntimeOverrideTests(unittest.TestCase):
    def test_override_can_change_at_runtime(self):
        manager = net.ProxyManager(ttl=0)
        with mock.patch.dict(os.environ, {"EMBYQT_PROXY": "http://127.0.0.1:7897"}, clear=False):
            self.assertIsNotNone(manager.current())
        with mock.patch.dict(os.environ, {"EMBYQT_PROXY": "none"}, clear=False):
            self.assertIsNone(manager.current())
