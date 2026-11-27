# -*- coding: utf-8 -*-
"""
BAZAR — GIF: «Мои GIF», поиск по интернету (GIPHY, через сервер) и отправка в личные чаты и группы.

Подключается из forum.py (install / start).

  • «Мои GIF» — личная коллекция (до 100 штук): можно сохранить GIF из любого чата (меню сообщения → «Сохранить в мои GIF»),
    из результатов поиска или загрузить с телефона. Лежат в таблице forum_gifs (создаётся сама).
  • Поиск и «Популярные» — GIPHY. Ключ в переменной окружения GIPHY_API_KEY (без неё поиск выключен, «Мои GIF» работают).
    Приложение ходит только на ваш сервер: запросы к GIPHY делает сервер, адрес и IP пользователя GIPHY не видит.
  • Отправка: в POST /messages и POST /groups/send добавлено поле gif — «s<id>» (из «Моих GIF») или «g<id GIPHY>».
    GIF уходит обычным вложением (image/gif, имя gif.gif), поэтому мини-апп показывает его как обычную картинку.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import struct
from collections import OrderedDict
from urllib.parse import urlparse

from aiohttp import web

import forum as F
from forum import FErr, J, api, jbody, to_int

P = F.P

DDL = """
CREATE TABLE IF NOT EXISTS forum_gifs(
    id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, data BYTEA NOT NULL, mime TEXT NOT NULL, sha TEXT NOT NULL,
    w INT NOT NULL DEFAULT 0, h INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), used_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS forum_gifs_user_sha_idx ON forum_gifs(user_id, sha);
CREATE INDEX IF NOT EXISTS forum_gifs_user_idx ON forum_gifs(user_id, used_at DESC);
"""

GIF_MAX = 8 * 1024 * 1024            # один GIF (из интернета и из своих файлов)
PREVIEW_MAX = 1536 * 1024            # превью в сетке поиска
SAVED_MAX = 100                      # «Моих GIF» на человека
PAGE = 24
GIPHY = "https://api.giphy.com/v1/gifs"
ID_RE = re.compile(r"[A-Za-z0-9]{3,40}")
_meta: "OrderedDict[str, dict]" = OrderedDict()      # id GIPHY -> {pv, send, w, h}
_pv: "OrderedDict[str, bytes]" = OrderedDict()       # id GIPHY -> байты превью
_sess = None


def api_key():
    return os.environ.get("GIPHY_API_KEY", "").strip()


def rating():
    r = os.environ.get("GIF_RATING", "pg-13").strip().lower()
    return r if r in ("g", "pg", "pg-13", "r") else "pg-13"


# ============================================================================ чистые функции (покрыты тестами)
def gif_info(data):
    """(mime, w, h) для настоящего GIF, иначе None. Тип берём из содержимого."""
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    w, h = struct.unpack("<HH", data[6:10])
    return "image/gif", w, h


def host_ok(url):
    """Качаем только с https-адресов giphy.com (защита от подмены адреса в ответе)."""
    try:
        u = urlparse(str(url))
    except ValueError:
        return False
    h = (u.hostname or "").lower()
    return u.scheme == "https" and (h == "giphy.com" or h.endswith(".giphy.com")) and u.port in (None, 443)


def _pick(images, names, cap=None):
    """Первый подходящий вариант картинки из images (url, ширина, высота), с проверкой хоста и размера."""
    for n in names:
        v = images.get(n) if isinstance(images, dict) else None
        if not isinstance(v, dict) or not host_ok(v.get("url")):
            continue
        size = to_int(v.get("size"))
        if cap and size and size > cap:
            continue
        return {"url": v["url"], "w": to_int(v.get("width")), "h": to_int(v.get("height"))}
    return None


def parse_items(js):
    """Ответ GIPHY → список {id, pv, send, w, h}. Элементы без превью или без годного для отправки GIF отбрасываем."""
    out = []
    for it in (js.get("data") if isinstance(js, dict) else None) or []:
        gid = str(it.get("id") or "") if isinstance(it, dict) else ""
        if not ID_RE.fullmatch(gid):
            continue
        im = it.get("images") or {}
        pv = _pick(im, ("fixed_width_small", "fixed_width", "preview_gif"), PREVIEW_MAX)
        send = _pick(im, ("downsized", "fixed_width", "downsized_medium"), GIF_MAX)
        if pv and send:
            out.append({"id": gid, "pv": pv["url"], "send": send["url"], "w": send["w"] or pv["w"], "h": send["h"] or pv["h"]})
    return out


def _remember(items):
    for x in items:
        _meta[x["id"]] = x
        _meta.move_to_end(x["id"])
    while len(_meta) > 600:
        _meta.popitem(last=False)


# ============================================================================ подписи и сеть
def _sig(kind, ident):
    return F.bm.img_url(kind, ident).split("t=")[1]


def _sig_ok(request, kind, ident):
    return hmac.compare_digest(request.query.get("t", ""), _sig(kind, ident))


async def _session():
    global _sess
    if _sess is None or _sess.closed:
        import aiohttp
        _sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), headers={"User-Agent": "KMBPForum/1.0"})
    return _sess


async def _fetch(url, cap):
    if not host_ok(url):
        raise FErr(400, "bad_gif", "Недопустимый адрес GIF")
    try:
        s = await _session()
        async with s.get(url, allow_redirects=False) as r:
            if r.status != 200:
                raise FErr(502, "gif_unavailable", "GIF сейчас недоступен")
            buf = bytearray()
            async for chunk in r.content.iter_chunked(64 * 1024):
                buf += chunk
                if len(buf) > cap:
                    raise FErr(400, "bad_size", "GIF слишком большой")
            return bytes(buf)
    except FErr:
        raise
    except Exception:
        raise FErr(502, "gif_unavailable", "GIF сейчас недоступен")


async def _giphy(path, params):
    key = api_key()
    if not key:
        raise FErr(503, "gif_off", "Поиск GIF не подключён")
    try:
        s = await _session()
        async with s.get(GIPHY + path, params={"api_key": key, **params}) as r:
            if r.status == 429:
                raise FErr(429, "too_fast", "GIPHY просит подождать — попробуйте через минуту")
            if r.status != 200:
                raise FErr(502, "gif_unavailable", "Поиск GIF сейчас недоступен")
            return await r.json(content_type=None)
    except FErr:
        raise
    except Exception:
        raise FErr(502, "gif_unavailable", "Поиск GIF сейчас недоступен")


async def _meta_of(gid):
    if not ID_RE.fullmatch(gid or ""):
        raise FErr(404, "not_found", "GIF не найден")
    if gid in _meta:
        return _meta[gid]
    js = await _giphy("/" + gid, {})
    d = js.get("data") if isinstance(js, dict) else None
    items = parse_items({"data": [d] if isinstance(d, dict) else []})
    if not items:
        raise FErr(404, "not_found", "GIF не найден")
    _remember(items)
    return items[0]


def _gif_item(x):
    return {"id": "g" + x["id"], "w": x["w"], "h": x["h"], "p": "/forum/api/gifs/pv/%s?t=%s" % (x["id"], _sig("gp", x["id"]))}


# ============================================================================ API
@api
async def a_gif_mine(request):
    me = request["fuid"]
    rows = await P().fetch("SELECT id,w,h FROM forum_gifs WHERE user_id=$1 ORDER BY used_at DESC, id DESC LIMIT $2", me, SAVED_MAX)
    return J({"web": bool(api_key()), "items": [
        {"id": "s%d" % r["id"], "w": r["w"], "h": r["h"], "p": "/forum/api/gifs/img/%d?t=%s" % (r["id"], _sig("gf", r["id"]))} for r in rows]})


@api
async def a_gif_search(request):
    """Поиск (q) или «Популярные» (q пустой). pos — смещение для подгрузки."""
    me = request["fuid"]
    if not api_key():
        return J({"off": True, "items": [], "next": ""})
    if not F.bm.rate_ok(("fgifq", me), 0.4):
        raise FErr(429, "too_fast", "Не так быстро")
    q = " ".join(str(request.query.get("q") or "").split())[:60]
    pos = max(0, min(to_int(request.query.get("pos")), 480))
    params = {"limit": PAGE, "offset": pos, "rating": rating(), "lang": "ru"}
    if q:
        params["q"] = q
    js = await _giphy("/search" if q else "/trending", params)
    got = len(js.get("data") or []) if isinstance(js, dict) else 0
    items = parse_items(js)
    _remember(items)
    total = to_int(((js.get("pagination") or {}) if isinstance(js, dict) else {}).get("total_count"), 10 ** 9)
    nxt = pos + got if got >= PAGE and pos + got < min(total, 500) else ""
    return J({"items": [_gif_item(x) for x in items], "next": str(nxt)})


async def a_gif_pv(request):
    """Превью из поиска (подписанная ссылка — <img> не шлёт заголовки): сервер скачивает у GIPHY и кэширует."""
    gid = request.match_info.get("gid", "")
    if not ID_RE.fullmatch(gid) or not _sig_ok(request, "gp", gid):
        raise web.HTTPNotFound()
    data = _pv.get(gid)
    if data is None:
        try:
            data = await _fetch((await _meta_of(gid))["pv"], PREVIEW_MAX)
        except FErr:
            raise web.HTTPNotFound()
        _pv[gid] = data
        while len(_pv) > 160:
            _pv.popitem(last=False)
    return web.Response(body=data, content_type="image/gif",
                        headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


async def a_gif_img(request):
    gid = to_int(request.match_info.get("gid"))
    if not gid or not _sig_ok(request, "gf", gid):
        raise web.HTTPNotFound()
    r = await P().fetchrow("SELECT data,mime FROM forum_gifs WHERE id=$1", gid)
    if not r:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(r["data"]), content_type=r["mime"],
                        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


async def _save(me, data):
    info = gif_info(data) if data else None
    if not info:
        raise FErr(400, "bad_gif", "Нужен GIF-файл")
    if len(data) > GIF_MAX:
        raise FErr(400, "bad_size", "GIF слишком большой (до %d МБ)" % (GIF_MAX // 1048576))
    sha = hashlib.sha1(data).hexdigest()
    old = await P().fetchval("UPDATE forum_gifs SET used_at=now() WHERE user_id=$1 AND sha=$2 RETURNING id", me, sha)
    if old:
        return old
    if await P().fetchval("SELECT count(*) FROM forum_gifs WHERE user_id=$1", me) >= SAVED_MAX:
        raise FErr(400, "limit", "В «Моих GIF» не больше %d — удалите ненужные" % SAVED_MAX)
    return await P().fetchval(
        "INSERT INTO forum_gifs(user_id,data,mime,sha,w,h) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT (user_id, sha) DO UPDATE SET used_at=now() RETURNING id",
        me, data, info[0], sha, info[1], info[2])


@api
async def a_gif_save(request):
    """Сохранить GIF: файл (multipart, поле file), GIF из сообщения {scope: dm|g, mid, gid} или из поиска {ref: g…}."""
    me = request["fuid"]
    if not F.bm.rate_ok(("fgifs", me), 0.6):
        raise FErr(429, "too_fast", "Не так быстро")
    if (request.content_type or "").startswith("multipart/"):
        f = (await request.post()).get("file")
        if f is None or not hasattr(f, "file"):
            raise FErr(400, "no_file", "Файл не выбран")
        data = f.file.read()
    else:
        d = await jbody(request)
        ref = str(d.get("ref") or "")
        if ref[:1] == "g":
            data = await _fetch((await _meta_of(ref[1:]))["send"], GIF_MAX)
        elif d.get("scope") == "g":
            import forum_groups
            gid = to_int(d.get("gid"))
            await forum_groups.ctx(me, gid, "see")
            row = await P().fetchrow("SELECT file_data FROM forum_group_msgs WHERE id=$1 AND group_id=$2", to_int(d.get("mid")), gid)
            data = bytes(row["file_data"]) if row and row["file_data"] else None
        else:
            row = await P().fetchrow(
                "SELECT file_data FROM direct_messages WHERE id=$1 AND (sender_id=$2 OR recipient_id=$2)", to_int(d.get("mid")), me)
            data = bytes(row["file_data"]) if row and row["file_data"] else None
        if not data:
            raise FErr(404, "not_found", "GIF не найден")
    return J({"ok": True, "id": "s%d" % await _save(me, data)})


@api
async def a_gif_delete(request):
    me = request["fuid"]
    ref = str((await jbody(request)).get("id") or "")
    if ref[:1] == "s" and ref[1:].isdigit():
        await P().execute("DELETE FROM forum_gifs WHERE id=$1 AND user_id=$2", int(ref[1:]), me)
    return J({"ok": True})


async def for_send(me, ref):
    """Для POST /messages и /groups/send: ссылка на GIF → (байты, mime, имя файла)."""
    ref = str(ref or "")
    if ref[:1] == "s" and ref[1:].isdigit():
        r = await P().fetchrow("UPDATE forum_gifs SET used_at=now() WHERE id=$1 AND user_id=$2 RETURNING data,mime", int(ref[1:]), me)
        if not r:
            raise FErr(404, "not_found", "GIF не найден")
        return bytes(r["data"]), r["mime"], "gif.gif"
    if ref[:1] == "g" and ID_RE.fullmatch(ref[1:]):
        data = await _fetch((await _meta_of(ref[1:]))["send"], GIF_MAX)
        if not gif_info(data):
            raise FErr(502, "gif_unavailable", "GIF сейчас недоступен")
        return data, "image/gif", "gif.gif"
    raise FErr(400, "bad_gif", "GIF не найден")


# ============================================================================ подключение
def install(r, A):
    r.add_get(A + "/gifs/mine", a_gif_mine)
    r.add_get(A + "/gifs/search", a_gif_search)
    r.add_post(A + "/gifs/save", a_gif_save)
    r.add_post(A + "/gifs/delete", a_gif_delete)
    r.add_get(A + "/gifs/img/{gid}", a_gif_img)
    r.add_get(A + "/gifs/pv/{gid}", a_gif_pv)
