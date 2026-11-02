import unittest

from embyqt.api import EmbyClient
from embyqt.streamproxy import StreamProxy


class StreamProgressTests(unittest.TestCase):
    def setUp(self):
        self.proxy = StreamProxy(EmbyClient("http://127.0.0.1:1", "test"))

    def test_downloaded_bytes_accumulate(self):
        self.proxy.begin_playback("item", 1000)
        self.proxy.add_progress("item", 100)
        self.proxy.add_progress("item", 50)
        self.proxy.set_progress_total("item", 50)
        self.assertEqual(self.proxy.bytes_for("item"), 150)

    def test_begin_playback_resets(self):
        self.proxy.begin_playback("item", 1000)
        self.proxy.add_progress("item", 300)
        self.proxy.begin_playback("item", 1000)
        self.assertEqual(self.proxy.bytes_for("item"), 0)
        self.assertEqual(self.proxy.windows_for("item"), [])

    def test_unknown_item(self):
        self.assertEqual(self.proxy.bytes_for("missing"), 0)

    def test_windows_and_merge(self):
        self.proxy.begin_playback("item", 1000)
        key = self.proxy.begin_request("item", 0)
        self.proxy.add_progress("item", 300, key)
        key2 = self.proxy.begin_request("item", 300)
        self.proxy.add_progress("item", 200, key2)
        self.assertEqual(self.proxy.windows_for("item"), [(0.0, 50.0)])

    def test_end_probe_does_not_hide_data_window(self):
        self.proxy.begin_playback("item", 1000)
        data = self.proxy.begin_request("item", 0)
        self.proxy.add_progress("item", 100, data)
        probe = self.proxy.begin_request("item", 990)
        self.proxy.add_progress("item", 10, probe)
        ranges = self.proxy.windows_for("item")
        self.assertIn((0.0, 10.0), ranges)
        self.assertIn((99.0, 100.0), ranges)

    def test_seek_within_buffer_keeps_windows(self):
        self.proxy.begin_playback("item", 1000)
        key = self.proxy.begin_request("item", 0)
        self.proxy.add_progress("item", 800, key)
        self.assertTrue(self.proxy.begin_seek("item", 50.0))
        self.assertEqual(len(self.proxy.windows_for("item")), 1)

    def test_seek_outside_buffer_clears_windows(self):
        self.proxy.begin_playback("item", 1000)
        key = self.proxy.begin_request("item", 0)
        self.proxy.add_progress("item", 100, key)
        self.assertFalse(self.proxy.begin_seek("item", 50.0))
        self.assertEqual(self.proxy.windows_for("item"), [])
        # 新请求从目标重新开始
        key2 = self.proxy.begin_request("item", 500)
        self.proxy.add_progress("item", 100, key2)
        self.assertEqual(self.proxy.windows_for("item"), [(50.0, 60.0)])


if __name__ == "__main__":
    unittest.main()
