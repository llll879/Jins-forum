# -*- coding: utf-8 -*-
"""Общее оформление канала: проверка и разбор стиля (чистые функции, без aiohttp и БД)."""
import json
import re

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_PRESET = re.compile(r"^[a-z]{2,16}$")
_PATTERNS = ("none", "dots", "grid", "stars", "waves", "rhomb")


def _num(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
        return default
    return int(min(hi, max(lo, round(v))))


def clean_style(raw, has_wp, wp_rev):
    """Оформление канала (та же структура, что разбирает chatstyle.js): обои, цвет сообщений канала, форма и размер текста.
    Всё лишнее отбрасываем; обои-фото возможны, только если фото загружено (тогда v = 'srv:<версия фото>')."""
    if not isinstance(raw, dict):
        return None
    w = raw.get("wp") if isinstance(raw.get("wp"), dict) else {}
    n = raw.get("inc") if isinstance(raw.get("inc"), dict) else {}
    t, v = w.get("t"), w.get("v")
    v = v if isinstance(v, str) else ""
    if t == "p" and _PRESET.match(v):
        pass
    elif t == "color" and _HEX.match(v):
        pass
    elif t == "img" and has_wp:
        v = "srv:%d" % wp_rev
    else:
        t, v = "none", ""
    pat = w.get("pat") if w.get("pat") in _PATTERNS else "none"
    c = n.get("c")
    return {"wp": {"t": t, "v": v, "blur": _num(w.get("blur"), 0, 20, 0), "dim": _num(w.get("dim"), 0, 80, 0),
                   "pat": pat, "pop": _num(w.get("pop"), 5, 50, 20)},
            "inc": {"c": c if isinstance(c, str) and _HEX.match(c) else ""},
            "rad": _num(raw.get("rad"), 4, 28, 20), "tail": 0 if raw.get("tail") == 0 else 1,
            "fs": _num(raw.get("fs"), 13, 20, 15), "gap": _num(raw.get("gap"), 2, 16, 7)}


def style_of(g):
    """Сохранённое оформление канала для клиента (или None, если админ его не задавал)."""
    try:
        st = json.loads(g["style"]) if g["style"] else None
    except ValueError:
        return None
    return st if isinstance(st, dict) else None
