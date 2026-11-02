"""API 层单元测试（不依赖网络）。

运行：.venv/bin/python -m unittest discover -s tests -v
"""

import json
import unittest

from embyqt.api import (
    EmbyClient,
    EmbyError,
    _error_message,
    build_server_url,
    format_ticks,
    image_url,
    normalize_server,
    parse_runtime,
)
from embyqt.streamproxy import StreamProxy


class FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class NormalizeServerTests(unittest.TestCase):
    def test_adds_scheme(self):
        self.assertEqual(normalize_server("emby.example.com"), "https://emby.example.com")

    def test_keeps_http(self):
        self.assertEqual(normalize_server("http://emby.local:8096/"), "http://emby.local:8096")

    def test_empty(self):
        self.assertEqual(normalize_server(""), "")


class BuildServerUrlTests(unittest.TestCase):
    def test_plain_host(self):
        self.assertEqual(build_server_url("emby.example.com"), "https://emby.example.com")

    def test_port_argument(self):
        self.assertEqual(
            build_server_url("emby.example.com", "8096"),
            "https://emby.example.com:8096",
        )

    def test_explicit_port_wins(self):
        self.assertEqual(
            build_server_url("http://emby.example.com:8097", "8096"),
            "http://emby.example.com:8097",
        )

    def test_http_scheme_kept(self):
        self.assertEqual(build_server_url("http://host", "80"), "http://host:80")

    def test_sub_path_kept(self):
        self.assertEqual(
            build_server_url("https://host/emby/", "8443"),
            "https://host:8443/emby",
        )

    def test_invalid_port(self):
        with self.assertRaises(ValueError):
            build_server_url("host", "abc")
        with self.assertRaises(ValueError):
            build_server_url("host", "70000")

    def test_empty(self):
        self.assertEqual(build_server_url(""), "")


class ImageUrlTests(unittest.TestCase):
    def test_primary_with_tag_and_width(self):
        url = image_url("https://s", "42", "Primary", tag="abc", max_width=320)
        self.assertTrue(url.startswith("https://s/Items/42/Images/Primary?"))
        self.assertIn("tag=abc", url)
        self.assertIn("maxWidth=320", url)

    def test_backdrop_index(self):
        url = image_url("https://s", "42", "Backdrop", index=0, max_width=1600)
        self.assertIn("/Images/Backdrop/0?", url)

    def test_empty_inputs(self):
        self.assertEqual(image_url("", "42"), "")
        self.assertEqual(image_url("https://s", ""), "")


class ClientUrlTests(unittest.TestCase):
    def setUp(self):
        self.client = EmbyClient("https://s", "device-1", token="tok")
        self.client.user = {"Id": "u1", "Name": "user"}

    def test_stream_path(self):
        path = self.client.stream_path("9", "mediasource_9", "ps-1")
        self.assertIn("/Videos/9/stream?", path)
        self.assertIn("static=true", path)
        self.assertIn("MediaSourceId=mediasource_9", path)
        self.assertIn("PlaySessionId=ps-1", path)

    def test_subtitle_path_normalizes_codec(self):
        self.assertIn("Stream.srt", self.client.subtitle_path("9", "ms", 3, "subrip"))
        self.assertIn("Stream.sup", self.client.subtitle_path("9", "ms", 3, "pgssub"))

    def test_authorization_header_contains_allowed_client(self):
        header = self.client.authorization_header()
        self.assertIn('Client="Emby for Android"', header)
        self.assertIn('Token="tok"', header)
        self.assertIn('DeviceId="device-1"', header)

    def test_item_image_prefers_tag(self):
        item = {"Id": "7", "ImageTags": {"Primary": "tag1"}}
        self.assertIn("tag=tag1", self.client.item_image(item, "Primary"))

    def test_item_image_without_tag(self):
        self.assertEqual(self.client.item_image({"Id": "7", "ImageTags": {}}), "")


class RuntimeFormatTests(unittest.TestCase):
    def test_parse_runtime_hours(self):
        self.assertEqual(parse_runtime(2 * 3600 * 10_000_000), "2 小时 0 分")

    def test_parse_runtime_minutes(self):
        self.assertEqual(parse_runtime(95 * 60 * 10_000_000), "1 小时 35 分")

    def test_parse_runtime_empty(self):
        self.assertEqual(parse_runtime(0), "")

    def test_format_ticks(self):
        self.assertEqual(format_ticks(65 * 10_000_000), "1:05")
        self.assertEqual(format_ticks(3725 * 10_000_000), "1:02:05")


class ErrorMessageTests(unittest.TestCase):
    def test_unauthorized(self):
        self.assertIn("认证失败", _error_message(FakeResponse(401, "")))

    def test_whitelist_block(self):
        message = _error_message(FakeResponse(403, "请使用群公告中允许的客户端进行访问"))
        self.assertIn("允许的客户端", message)

    def test_json_message(self):
        response = FakeResponse(500, json.dumps({"message": "boom"}), {"message": "boom"})
        self.assertEqual(_error_message(response), "boom")


class StreamProxyUrlTests(unittest.TestCase):
    def test_media_url(self):
        client = EmbyClient("https://s", "device-1", token="tok")
        client.user = {"Id": "u1"}
        proxy = StreamProxy(client)
        proxy.port = 4321
        url = proxy.media_url("9", "mediasource_9", "ps-1")
        self.assertTrue(url.startswith("http://127.0.0.1:4321/media/9?"))
        self.assertIn("src=mediasource_9", url)
        self.assertIn("psid=ps-1", url)

    def test_subtitle_url(self):
        client = EmbyClient("https://s", "device-1", token="tok")
        client.user = {"Id": "u1"}
        proxy = StreamProxy(client)
        proxy.port = 4321
        url = proxy.subtitle_url("9", "ms", 2, "srt")
        self.assertIn("/sub?p=", url)
        self.assertIn("Subtitles%2F2%2FStream.srt", url)


class ErrorTypeTests(unittest.TestCase):
    def test_emby_error_fields(self):
        error = EmbyError("msg", 403)
        self.assertEqual(error.status, 403)
        self.assertEqual(str(error), "msg")


if __name__ == "__main__":
    unittest.main()
