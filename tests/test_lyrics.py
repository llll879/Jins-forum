# -*- coding: utf-8 -*-
"""Разбор LRC для /music/lyrics. forum.py здесь не импортируется (нужны aiogram/БД) — вырезаем из исходника чистые функции.
Запуск: python -m unittest discover -s tests -v"""
import os
import re
import unittest

SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forum.py"), encoding="utf-8").read()
ns = {"re": re}
exec(SRC[SRC.index("_LRC_TS = "):SRC.index("async def _lrclib")], ns)


class Lrc(unittest.TestCase):
    def test_sorted_and_multistamp(self):
        r = ns["_lrc_parse"]("[ar:x]\n[00:05.20]Привет <00:06.00>мир\n[00:01.5][00:30.00]Хор\n[01:02]Конец")
        self.assertEqual(r, [[1.5, "Хор"], [5.2, "Привет мир"], [30.0, "Хор"], [62, "Конец"]])

    def test_leading_blank_dropped_gap_kept(self):
        r = ns["_lrc_parse"]("[00:01.00]\n[00:02.00]А\n[00:09.00]\n[00:12.00]Б")
        self.assertEqual([x[1] for x in r], ["А", "", "Б"])

    def test_empty(self):
        self.assertEqual(ns["_lrc_parse"](""), [])
        self.assertEqual(ns["_lrc_parse"](None), [])

    def test_title_core(self):
        self.assertEqual(ns["_title_core"]("Песня (feat. X) [Remix]"), "Песня")


if __name__ == "__main__":
    unittest.main()
