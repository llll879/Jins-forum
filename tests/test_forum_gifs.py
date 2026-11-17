# -*- coding: utf-8 -*-
"""Чистые функции GIF и анимированных стикеров. Запуск: python -m unittest discover -s tests -v
Модули forum / aiohttp здесь подменяются заглушками — база и сеть не нужны."""
import os
import struct
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stub():
    if "aiohttp" not in sys.modules:
        m = types.ModuleType("aiohttp")
        m.web = types.SimpleNamespace(HTTPNotFound=Exception, Response=object, middleware=lambda f: f)
        sys.modules["aiohttp"] = m
    if "forum" not in sys.modules or not hasattr(sys.modules["forum"], "FErr"):
        f = types.ModuleType("forum")
        f.P = lambda: None
        f.FErr = type("FErr", (Exception,), {})
        f.J = f.jbody = f.ghost = f.users_map = lambda *a, **k: None
        f.to_int = lambda v, default=0: int(v) if str(v).lstrip("-").isdigit() else default
        f.api = lambda fn=None, **k: fn if fn else (lambda g: g)
        sys.modules["forum"] = f


_stub()
import forum_names  # noqa: E402,F401  (настоящий, чистый модуль)
import forum_gifs as G      # noqa: E402
import forum_groups as FG   # noqa: E402


def png(chunks):
    out = b"\x89PNG\r\n\x1a\n"
    for t, body in chunks:
        out += struct.pack(">I", len(body)) + t + body + b"\0\0\0\0"
    return out


GIF = b"GIF89a" + struct.pack("<HH", 320, 200) + b"\0" * 20
WEBM = b"\x1a\x45\xdf\xa3" + b"\x9f\x42\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84webm" + b"\0" * 40
MKV = WEBM.replace(b"webm", b"matr")
WEBP_ANIM = b"RIFF\0\0\0\0WEBPVP8X" + struct.pack("<I", 10) + bytes([0x12]) + b"\0" * 20
WEBP_STILL = b"RIFF\0\0\0\0WEBPVP8X" + struct.pack("<I", 10) + bytes([0x10]) + b"\0" * 20
APNG = png([(b"IHDR", b"\0" * 13), (b"acTL", b"\0" * 8), (b"IDAT", b"x")])
PNG = png([(b"IHDR", b"\0" * 13), (b"gAMA", b"\0" * 4), (b"IDAT", b"x"), (b"IEND", b"")])


class Stickers(unittest.TestCase):
    def test_mime(self):
        self.assertEqual(FG._img_mime(WEBM), "video/webm")
        self.assertIsNone(FG._img_mime(MKV))              # не WebM (например, mkv) не принимаем
        self.assertEqual(FG._img_mime(GIF), "image/gif")
        self.assertEqual(FG._img_mime(APNG), "image/png")
        self.assertIsNone(FG._img_mime(b"<svg onload=alert(1)>"))

    def test_anim(self):
        self.assertTrue(FG._is_anim(WEBM, "video/webm"))
        self.assertTrue(FG._is_anim(GIF, "image/gif"))
        self.assertTrue(FG._is_anim(WEBP_ANIM, "image/webp"))
        self.assertFalse(FG._is_anim(WEBP_STILL, "image/webp"))
        self.assertTrue(FG._is_anim(APNG, "image/png"))
        self.assertFalse(FG._is_anim(PNG, "image/png"))
        self.assertFalse(FG._is_anim(b"\xff\xd8\xff\xe0", "image/jpeg"))

    def test_png_garbage_does_not_hang(self):
        self.assertFalse(FG._is_anim(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 2 ** 31) + b"junk", "image/png"))


class Gifs(unittest.TestCase):
    def test_gif_info(self):
        self.assertEqual(G.gif_info(GIF), ("image/gif", 320, 200))
        self.assertIsNone(G.gif_info(WEBP_ANIM))
        self.assertIsNone(G.gif_info(b"GIF8"))
        self.assertIsNone(G.gif_info(b"<html>"))

    def test_host(self):
        for ok in ("https://media1.giphy.com/media/x/giphy.gif", "https://i.giphy.com/x.gif", "https://giphy.com/a.gif"):
            self.assertTrue(G.host_ok(ok), ok)
        for bad in ("http://media.giphy.com/x.gif", "https://evilgiphy.com/x.gif", "https://giphy.com.evil.io/x.gif",
                    "https://media.giphy.com@evil.io/x.gif", "https://127.0.0.1/x.gif", "https://media.giphy.com:8443/x.gif", "file:///etc/passwd", "", None):
            self.assertFalse(G.host_ok(bad), bad)

    def test_parse(self):
        def img(u, w, h, size):
            return {"url": u, "width": str(w), "height": str(h), "size": str(size)}
        js = {"data": [
            {"id": "abc123", "images": {"fixed_width_small": img("https://media0.giphy.com/s.gif", 100, 80, 50000),
                                        "downsized": img("https://media0.giphy.com/d.gif", 480, 380, 900000)}},
            {"id": "big", "images": {"fixed_width": img("https://media0.giphy.com/f.gif", 200, 160, 40000),
                                     "downsized": img("https://media0.giphy.com/d.gif", 480, 380, 99999999)}},
            {"id": "evil1", "images": {"fixed_width_small": img("https://evil.io/s.gif", 1, 1, 1), "downsized": img("https://evil.io/d.gif", 1, 1, 1)}},
            {"id": "bad id!", "images": {}},
            {"id": "nopv", "images": {"downsized": img("https://media0.giphy.com/d.gif", 1, 1, 1)}},
            "junk", None]}
        got = {x["id"]: x for x in G.parse_items(js)}
        self.assertEqual(set(got), {"abc123", "big"})
        self.assertEqual((got["abc123"]["w"], got["abc123"]["h"]), (480, 380))
        self.assertEqual(got["big"]["send"], "https://media0.giphy.com/f.gif")   # downsized больше лимита — берём fixed_width
        self.assertEqual(G.parse_items({}), [])
        self.assertEqual(G.parse_items(None), [])


if __name__ == "__main__":
    unittest.main()
