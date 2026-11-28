"""BAZAR WAVE: SoundCloud (НЕОФИЦИАЛЬНО, без ключей разработчика).

Работает через тот же публичный api-v2, что и сайт soundcloud.com: client_id берётся со страницы сайта
(или из переменной SC_CLIENT_ID, если задали вручную). Это нарушает условия использования SoundCloud и может
перестать работать при любом изменении сайта — поэтому всё изолировано в этом файле, а ошибки не роняют Яндекс.
id треков в плеере: "s" + число; id исполнителей: "s" + число.
Играются только треки с прогрессивным mp3 (HLS-only в <audio> на Android WebView не идёт).
"""
from __future__ import annotations

import logging
import os
import re
import time

import aiohttp

log = logging.getLogger("forum.sc")

API = "https://api-v2.soundcloud.com"
SITE = "https://soundcloud.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_cid = {"v": os.getenv("SC_CLIENT_ID", "").strip(), "ts": 0.0, "fixed": bool(os.getenv("SC_CLIENT_ID", "").strip())}


def _ses():
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12), trust_env=False,
                                 headers={"User-Agent": UA, "Accept": "application/json, text/html, */*"})


async def _scrape_cid():
    async with _ses() as s:
        async with s.get(SITE) as r:
            page = await r.text()
        urls = re.findall(r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', page)
        for u in reversed(urls):                       # client_id обычно в одном из последних бандлов
            try:
                async with s.get(u) as r:
                    js = await r.text()
            except Exception:
                continue
            m = re.search(r'client_id\s*[:=]\s*"([A-Za-z0-9]{20,40})"', js)
            if m:
                return m.group(1)
    return ""


async def client_id(force=False):
    if _cid["fixed"]:
        return _cid["v"]
    if force or not _cid["v"] or time.monotonic() - _cid["ts"] > 6 * 3600:
        v = await _scrape_cid()
        if v:
            _cid["v"], _cid["ts"] = v, time.monotonic()
        elif not _cid["v"]:
            raise RuntimeError("не удалось получить client_id SoundCloud")
    return _cid["v"]


async def _get(path, params=None, full=None):
    """GET с автообновлением client_id при 401/403."""
    for attempt in (0, 1):
        cid = await client_id(force=attempt == 1)
        p = dict(params or {})
        p["client_id"] = cid
        async with _ses() as s:
            async with s.get(full or (API + path), params=p) as r:
                if r.status in (401, 403) and attempt == 0 and not _cid["fixed"]:
                    continue
                if r.status != 200:
                    raise RuntimeError("soundcloud %s" % r.status)
                return await r.json(content_type=None)
    raise RuntimeError("soundcloud: нет доступа")


def _img(u, size="t300x300"):
    if not u:
        return ""
    return re.sub(r"-(large|crop|t\d+x\d+|badge|small|tiny|mini)\.", "-%s." % size, u, count=1)


def _playable(t):
    for tc in ((t.get("media") or {}).get("transcodings") or []):
        f = tc.get("format") or {}
        if f.get("protocol") == "progressive":
            return True
    return False


def norm(tracks):
    out = []
    for t in tracks or []:
        try:
            if not t or t.get("kind", "track") != "track" or not t.get("id"):
                continue
            if t.get("policy") in ("BLOCK", "SNIP") or not _playable(t):
                continue
            u = t.get("user") or {}
            uid = ("s" + str(u["id"])) if u.get("id") else ""
            name = (u.get("username") or "")[:200]
            out.append({"id": "s" + str(t["id"]), "ai": uid, "ax": [[uid, name]] if uid and name else [],
                        "t": (t.get("title") or "")[:200], "a": name,
                        "img": _img(t.get("artwork_url") or u.get("avatar_url") or ""),
                        "d": max(0, int((t.get("duration") or 0) // 1000)), "u": ""})
        except Exception:
            continue
    return out


async def search_tracks(q, limit=20):
    d = await _get("/search/tracks", {"q": q, "limit": min(limit, 40)})
    return norm(d.get("collection"))


async def search_artists(q, limit=6):
    d = await _get("/search/users", {"q": q, "limit": limit})
    return [{"id": "s" + str(u["id"]), "name": (u.get("username") or "")[:200], "img": _img(u.get("avatar_url"), "t200x200")}
            for u in (d.get("collection") or []) if u.get("id") and u.get("username")]


async def chart(kind="top", genre="soundcloud:genres:all-music", limit=30):
    d = await _get("/charts", {"kind": kind if kind in ("top", "trending") else "top", "genre": genre, "limit": min(limit, 50)})
    return norm([x.get("track") for x in (d.get("collection") or [])])


async def artist(uid):
    u = await _get("/users/%s" % uid)
    try:
        d = await _get("/users/%s/tracks" % uid, {"limit": 50})
        tracks = norm(d.get("collection"))
    except Exception as e:
        log.warning("sc artist tracks: %s", e)
        tracks = []
    try:
        d = await _get("/users/%s/toptracks" % uid, {"limit": 10})
        top = norm(d.get("collection"))
    except Exception:
        top = []
    sub = []
    if u.get("followers_count"):
        sub.append("%s подписчиков" % f"{int(u['followers_count']):,}".replace(",", " "))
    return {"artist": {"id": "s" + str(uid), "name": u.get("username") or "", "img": _img(u.get("avatar_url"), "t500x500"),
                       "sub": " · ".join(sub), "genres": []},
            "top": (top or tracks)[:10], "tracks": tracks or top, "similar": [], "sim_artists": []}


async def stream_url(tid):
    """Прямой адрес mp3 (временный). '' — если у трека нет прогрессивного потока."""
    t = await _get("/tracks/%s" % tid)
    tcs = [tc for tc in ((t.get("media") or {}).get("transcodings") or []) if (tc.get("format") or {}).get("protocol") == "progressive"]
    if not tcs:
        return ""
    tcs.sort(key=lambda tc: "mpeg" not in ((tc.get("format") or {}).get("mime_type") or ""))
    params = {}
    if t.get("track_authorization"):
        params["track_authorization"] = t["track_authorization"]
    d = await _get("", params, full=tcs[0]["url"])
    u = d.get("url") or ""
    return u if u.startswith("https://") else ""
