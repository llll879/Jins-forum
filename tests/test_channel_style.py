# -*- coding: utf-8 -*-
"""Общее оформление канала: проверка стиля на сервере. Запуск: python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forum_style as G


class ChannelStyle(unittest.TestCase):
    def test_garbage(self):
        for raw in (None, [], "x", 5):
            self.assertIsNone(G.clean_style(raw, False, 0))

    def test_clamps_and_defaults(self):
        st = G.clean_style({"wp": {"t": "p", "v": "sunset", "blur": 999, "dim": -5, "pat": "evil", "pop": "x"},
                            "inc": {"c": "#E8638B"}, "rad": 100, "fs": 1, "gap": True, "tail": 0}, False, 0)
        self.assertEqual(st["wp"], {"t": "p", "v": "sunset", "blur": 20, "dim": 0, "pat": "none", "pop": 20})
        self.assertEqual((st["inc"]["c"], st["rad"], st["fs"], st["gap"], st["tail"]), ("#E8638B", 28, 13, 7, 0))

    def test_bad_values_dropped(self):
        for w in ({"t": "color", "v": "red"}, {"t": "p", "v": "../../x"}, {"t": "img", "v": "srv:9"}, {"t": "zzz"}):
            self.assertEqual(G.clean_style({"wp": w}, False, 3)["wp"]["t"], "none", w)
        self.assertEqual(G.clean_style({"inc": {"c": "javascript:1"}}, False, 0)["inc"]["c"], "")

    def test_photo_needs_upload_and_gets_server_version(self):
        st = G.clean_style({"wp": {"t": "img", "v": "whatever"}}, True, 4)
        self.assertEqual((st["wp"]["t"], st["wp"]["v"]), ("img", "srv:4"))

    def test_style_of(self):
        self.assertIsNone(G.style_of({"style": None}))
        self.assertIsNone(G.style_of({"style": "{broken"}))
        self.assertEqual(G.style_of({"style": '{"rad": 9}'}), {"rad": 9})


if __name__ == "__main__":
    unittest.main()
