#!/usr/bin/env python3
"""Собирает forum.html из forum.src.html: подставляет спрайты из forum_assets/ как data-URI.

Запуск из корня проекта:  python tools/build_forum.py
Правите forum.src.html (вёрстка/стили/JS) или картинки в forum_assets/ — затем собираете заново.
"""
import base64, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "forum.src.html")
OUT = os.path.join(ROOT, "forum.html")
ASSETS = os.path.join(ROOT, "forum_assets")


def data_uri(name):
    for ext, mime in (("jpg", "image/jpeg"), ("png", "image/png"), ("webp", "image/webp")):
        p = os.path.join(ASSETS, f"{name}.{ext}")
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    sys.exit(f"нет картинки {name} в {ASSETS}")


with open(SRC, encoding="utf-8") as f:
    html = f.read()
html = re.sub(r"\{\{img:([\w-]+)\}\}", lambda m: data_uri(m.group(1)), html)


def include(m):
    """{{inc:путь}} — вставляет файл из tools/ как есть (редактор фото/видео)."""
    with open(os.path.join(ROOT, "tools", m.group(1)), encoding="utf-8") as f:
        return f.read().strip()


html = re.sub(r"\{\{inc:([\w./-]+)\}\}", include, html)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"OK: {OUT} ({os.path.getsize(OUT) // 1024} КБ)")
