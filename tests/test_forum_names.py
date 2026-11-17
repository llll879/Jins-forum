# -*- coding: utf-8 -*-
"""Чистые функции forum_names: разбор ссылок exg/… и проверка имён. Запуск: python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forum_names as N


class Names(unittest.TestCase):
    def test_clean(self):
        for raw in ("exg/Cats", "EXG/cats", "@Cats", "https://host.example/exg/Cats", "https://host.example/forum/exg/cats/",
                    "https://host.example/exg/cats?x=1#y", "  cats  "):
            self.assertEqual(N.clean(raw), "cats", raw)
        self.assertEqual(N.clean("exg/+AbC123def4"), "+abc123def4")

    def test_invite(self):
        self.assertEqual(N.invite_token("+abc123def4"), "abc123def4")
        self.assertIsNone(N.invite_token("abc123def4"))
        self.assertIsNone(N.invite_token("+a"))

    def test_valid(self):
        for ok in ("cats", "my_pack", "a1b2", "x" * 32):
            self.assertIsNone(N.valid(ok), ok)
        for bad in ("", "abc", "x" * 33, "1abc", "_abc", "привет", "a b c", "a-b-c", "admin", "exg"):
            self.assertIsNotNone(N.valid(bad), bad)


if __name__ == "__main__":
    unittest.main()
