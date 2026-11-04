"""主题切换的单元测试。"""

import unittest

from embyqt.ui import theme


class ThemeTests(unittest.TestCase):
    def tearDown(self):
        theme.set_scheme("dark")

    def test_dark_palette(self):
        theme.set_scheme("dark")
        self.assertEqual(theme.BG, "#0e1116")
        self.assertEqual(theme.SCHEME, "dark")
        self.assertIn(theme.TEXT, theme.STYLESHEET)

    def test_light_palette(self):
        theme.set_scheme("light")
        self.assertEqual(theme.BG, "#eef0f2")
        self.assertEqual(theme.SCHEME, "light")
        self.assertIn(theme.TEXT, theme.STYLESHEET)
        self.assertIn("QLabel#posterTitle", theme.STYLESHEET)

    def test_legacy_blue_maps_to_dark(self):
        theme.set_scheme("blue")
        self.assertEqual(theme.BG, "#0e1116")
        self.assertEqual(theme.SCHEME, "dark")
        self.assertEqual(theme.ACCENT, "#2f8cff")
        self.assertIn(theme.TEXT, theme.STYLESHEET)

    def test_unknown_falls_back_to_dark(self):
        theme.set_scheme("purple")
        self.assertEqual(theme.SCHEME, "dark")


if __name__ == "__main__":
    unittest.main()
