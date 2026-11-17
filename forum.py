# -*- coding: utf-8 -*-
"""
KMBP FORUM — вторая часть проекта: форум / соцсеть, синхронизированная с ботом и мини-аппом.

  • Работает в том же процессе и в той же базе, поэтому общие: аккаунты (users), аватар, баннер, описание, значки у ника,
    личные сообщения (direct_messages — это те же чаты, что в мини-аппе, включая «Поддержку»), блокировки.
  • Вход без паролей — через бота: приложение показывает код, пользователь нажимает «Войти через Telegram» (/start forum_КОД),
    бот подтверждает, приложение получает токен.
  • Клиент — один файл forum.html (без внешних библиотек). Отдаётся по /forum, скачивается с /forum/app.html?dl=1
    (адрес сервера уже вписан) и собирается в APK любым конвертером «HTML to APK».
  • API: /forum/api/* (JSON, заголовок Authorization: Bearer <token>, CORS открыт — нужен для APK).
"""
from __future__ import annotations

import asyncio
import html as _html
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

try:
    from aiogram import F, Router
    from aiogram.types import Message
    router = Router(name="forum")
except Exception:  # pragma: no cover
    router = None

log = logging.getLogger("jins.forum")
bm = None


def P():
    return bm.pool


def _base():
    """Публичный адрес ФОРУМА. Отдельный сервис -> задайте FORUM_URL; иначе берётся WEBAPP_URL (как раньше, когда всё было в одном процессе)."""
    return (os.getenv("FORUM_URL") or _auto_base or bm.WEBAPP_URL or "").rstrip("/")


_auto_base = ""      # адрес, по которому форум открыли в последний раз (если FORUM_URL не задан)


class FErr(Exception):
    def __init__(self, status, code, msg=""):
        self.status, self.code, self.msg = status, code, msg or code


def J(data, status=200):
    return web.json_response(data, status=status, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))


DDL = """
CREATE TABLE IF NOT EXISTS forum_sessions(token TEXT PRIMARY KEY, user_id BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_used TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS forum_sessions_user_idx ON forum_sessions(user_id);
CREATE TABLE IF NOT EXISTS forum_login(code TEXT PRIMARY KEY, user_id BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS forum_boards(id SERIAL PRIMARY KEY, name TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '💬', sort INT NOT NULL DEFAULT 0, admin_only BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS forum_posts(
    id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, board_id INT REFERENCES forum_boards(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), edited_at TIMESTAMPTZ,
    pinned BOOLEAN NOT NULL DEFAULT FALSE, views INT NOT NULL DEFAULT 0, deleted BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX IF NOT EXISTS forum_posts_feed_idx ON forum_posts(id DESC) WHERE NOT deleted;
CREATE INDEX IF NOT EXISTS forum_posts_user_idx ON forum_posts(user_id);
CREATE INDEX IF NOT EXISTS forum_posts_board_idx ON forum_posts(board_id);
CREATE TABLE IF NOT EXISTS forum_images(id SERIAL PRIMARY KEY, post_id INT NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE, data BYTEA NOT NULL, mime TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS forum_images_post_idx ON forum_images(post_id);
CREATE TABLE IF NOT EXISTS forum_comments(
    id SERIAL PRIMARY KEY, post_id INT NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE, user_id BIGINT NOT NULL, parent_id INT,
    body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX IF NOT EXISTS forum_comments_post_idx ON forum_comments(post_id, id);
ALTER TABLE forum_comments ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS forum_likes(user_id BIGINT NOT NULL, kind CHAR(1) NOT NULL, target_id INT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id, kind, target_id));
CREATE INDEX IF NOT EXISTS forum_likes_target_idx ON forum_likes(kind, target_id);
CREATE TABLE IF NOT EXISTS forum_follows(follower_id BIGINT NOT NULL, followee_id BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(follower_id, followee_id));
CREATE INDEX IF NOT EXISTS forum_follows_followee_idx ON forum_follows(followee_id);
CREATE TABLE IF NOT EXISTS forum_chat_prefs(
    user_id BIGINT NOT NULL, peer_id BIGINT NOT NULL, pinned_at TIMESTAMPTZ, muted BOOLEAN NOT NULL DEFAULT FALSE, archived BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY(user_id, peer_id));
CREATE TABLE IF NOT EXISTS forum_msg_reactions(
    msg_id BIGINT NOT NULL REFERENCES direct_messages(id) ON DELETE CASCADE, user_id BIGINT NOT NULL, emoji TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(msg_id, user_id));
CREATE TABLE IF NOT EXISTS forum_msg_posts(
    msg_id BIGINT PRIMARY KEY REFERENCES direct_messages(id) ON DELETE CASCADE, post_id INT NOT NULL);
CREATE TABLE IF NOT EXISTS forum_bookmarks(user_id BIGINT NOT NULL, post_id INT NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id, post_id));
CREATE TABLE IF NOT EXISTS forum_notifs(
    id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, kind TEXT NOT NULL, actor_id BIGINT NOT NULL, post_id INT, comment_id INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), read BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX IF NOT EXISTS forum_notifs_user_idx ON forum_notifs(user_id, id DESC);
CREATE TABLE IF NOT EXISTS forum_notif_prefs(
    user_id BIGINT PRIMARY KEY, likes BOOLEAN NOT NULL DEFAULT TRUE, comments BOOLEAN NOT NULL DEFAULT TRUE, mentions BOOLEAN NOT NULL DEFAULT TRUE,
    follows BOOLEAN NOT NULL DEFAULT TRUE, dms BOOLEAN NOT NULL DEFAULT TRUE, tg BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS forum_reports(
    id SERIAL PRIMARY KEY, reporter_id BIGINT NOT NULL, kind CHAR(1) NOT NULL, target_id INT NOT NULL, reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
"""

SEED_BOARDS = [("Новости", "📰", 1, True), ("Общий", "💬", 2, False), ("Вопросы", "❓", 3, False), ("Пиар", "📣", 4, False),
               ("Проекты", "🧩", 5, False), ("Флуд", "🎲", 6, False)]

TITLE_MAX, BODY_MAX, COMMENT_MAX, BIO_MAX, IMG_MAX = 120, 8000, 2000, 500, 4 * 1024 * 1024
# Медиа в постах: альбом до MEDIA_COUNT файлов (фото + видео), видео до VID_MAX, всего на пост до MEDIA_TOTAL
MEDIA_COUNT, VID_MAX, MEDIA_TOTAL = 10, 20 * 1024 * 1024, 40 * 1024 * 1024
POST_BODY_MAX = MEDIA_TOTAL + 4 * 1024 * 1024        # лимит тела запроса поста (глобальный client_max_size меньше)
_VIDEO_BAD_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis")
IMG_MIMES = ("image/jpeg", "image/png", "image/webp", "image/gif")
_seen_views = {}
_seen_touch = {}


# ============================================================================ CORS + авторизация
@web.middleware
async def cors_mw(request, handler):
    if not request.path.startswith("/forum/api/"):
        return await handler(request)
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


def api(fn=None, *, auth=True):
    """Обёртка эндпоинта: авторизация по Bearer-токену, единый формат ошибок."""
    def deco(f):
        async def wrapper(request):
            try:
                uid = await uid_of(request, auth)
                request["fuid"] = uid
                return await f(request)
            except FErr as e:
                return J({"error": e.code, "message": e.msg}, e.status)
            except web.HTTPException:
                raise
            except Exception:
                log.exception("forum api failed: %s", request.path)
                return J({"error": "server", "message": "Что-то пошло не так, попробуйте позже"}, 500)
        return wrapper
    return deco(fn) if fn else deco


async def uid_of(request, required=True):
    h = request.headers.get("Authorization") or ""
    tok = h[7:].strip() if h.lower().startswith("bearer ") else ""
    uid = 0
    if tok:
        uid = await P().fetchval("SELECT user_id FROM forum_sessions WHERE token=$1", tok) or 0
    if not uid and required:
        raise FErr(401, "auth", "Нужно войти")
    if uid and time.monotonic() - _seen_touch.get(uid, 0) > 60:
        _seen_touch[uid] = time.monotonic()
        if len(_seen_touch) > 5000:
            _seen_touch.clear()
        await P().execute("UPDATE users SET last_seen=now() WHERE user_id=$1", uid)
        await P().execute("UPDATE forum_sessions SET last_used=now() WHERE token=$1", tok)
    return uid


async def jbody(request):
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


async def is_staff(uid):
    return await bm.role(uid) is not None


# ============================================================================ пользователи
async def users_map(ids):
    ids = list({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = await P().fetch(
        "SELECT user_id,username,first_name,last_name,bio,accent,created_at,(avatar_data IS NOT NULL OR tg_avatar_data IS NOT NULL OR photo_url IS NOT NULL) av,"
        "(banner_data IS NOT NULL) bn,(banner_mime LIKE 'video/%') bnv FROM users WHERE user_id=ANY($1::bigint[])", ids)
    sb = await bm.staff_badges(ids)
    import forum_names
    hn = await forum_names.get_many("user", ids)          # внутренний юзернейм (exg/имя) главнее ника из Telegram
    out = {}
    for r in rows:
        uname = hn.get(r["user_id"]) or r["username"] or ""
        out[r["user_id"]] = {
            "id": r["user_id"], "username": uname, "own_name": r["user_id"] in hn,
            "name": " ".join(x for x in [r["first_name"], r["last_name"]] if x) or uname or "Пользователь",
            "av": bool(r["av"]), "bn": bool(r["bn"]), "bnv": bool(r["bnv"]), "sb": sb.get(r["user_id"], ""), "bio": r["bio"] or "", "accent": r["accent"] or ""}
    return out


def ghost(uid):
    return {"id": uid, "username": "", "own_name": False, "name": "Пользователь", "av": False, "bn": False, "bnv": False, "sb": "", "bio": "", "accent": ""}


async def me_json(uid):
    u = (await users_map([uid])).get(uid) or ghost(uid)
    u = dict(u)
    u["staff"] = await is_staff(uid)
    u["main"] = await bm.is_main(uid)
    return u


# ============================================================================ вход через бота
async def a_boot(request):
    boards = [dict(r) for r in await P().fetch("SELECT id,name,emoji,admin_only FROM forum_boards ORDER BY sort,id")]
    return J({"boards": boards, "bot": bm.BOT_USERNAME, "name": "KMBP FORUM"})


async def a_auth_start(request):
    await P().execute("DELETE FROM forum_login WHERE created_at < now() - interval '15 minutes'")
    code = secrets.token_hex(4)
    await P().execute("INSERT INTO forum_login(code) VALUES($1)", code)
    bot = bm.BOT_USERNAME
    return J({"code": code, "bot": bot, "link": f"https://t.me/{bot}?start=forum_{code}", "tg": f"tg://resolve?domain={bot}&start=forum_{code}"})


async def a_auth_poll(request):
    code = (request.query.get("code") or "").strip()
    row = await P().fetchrow("SELECT user_id FROM forum_login WHERE code=$1 AND created_at > now() - interval '15 minutes'", code)
    if not row:
        return J({"status": "expired"})
    if not row["user_id"]:
        return J({"status": "wait"})
    tok = secrets.token_urlsafe(32)
    await P().execute("INSERT INTO forum_sessions(token,user_id) VALUES($1,$2)", tok, row["user_id"])
    await P().execute("DELETE FROM forum_login WHERE code=$1", code)
    return J({"status": "ok", "token": tok, "me": await me_json(row["user_id"])})


@api
async def a_logout(request):
    h = request.headers.get("Authorization") or ""
    await P().execute("DELETE FROM forum_sessions WHERE token=$1", h[7:].strip())
    return J({"ok": True})


@api
async def a_me(request):
    uid = request["fuid"]
    return J({"me": await me_json(uid)})


if router is not None:
    @router.message(F.text.startswith("/start forum_"), F.chat.type == "private")
    async def bot_forum_login(m: Message):
        code = m.text.split("forum_", 1)[1].strip()[:8]
        if not re.fullmatch(r"[0-9a-f]{8}", code):
            await m.answer("Код входа некорректный. Вернитесь в приложение и нажмите «Войти через Telegram» ещё раз.")
            return
        await bm.register_user(m.from_user)
        ok = await P().fetchval(
            "UPDATE forum_login SET user_id=$2 WHERE code=$1 AND user_id IS NULL AND created_at > now() - interval '15 minutes' RETURNING code", code, m.from_user.id)
        if ok:
            await m.answer("✅ <b>Вход в KMBP FORUM подтверждён.</b>\nВозвращайтесь в приложение — оно откроется само.")
        else:
            await m.answer("Код входа устарел или уже использован. Вернитесь в приложение и нажмите «Войти через Telegram» ещё раз.")


# ============================================================================ профиль
@api
async def a_me_update(request):
    uid = request["fuid"]
    d = await jbody(request)
    import forum_names
    if "username" in d:                      # внутренний юзернейм: ссылка exg/имя; пустой — остаётся ник из Telegram
        raw = str(d.get("username") or "").strip()
        if raw:
            if not bm.rate_ok(("fname", uid), 3):
                raise FErr(429, "too_fast", "Не так быстро")
            await forum_names.put("user", uid, await forum_names.check(raw, "user", uid))
        else:
            await forum_names.drop("user", uid)
    if "bio" in d:
        await P().execute("UPDATE users SET bio=$2 WHERE user_id=$1", uid, str(d.get("bio") or "").strip()[:BIO_MAX])
    return J({"me": await me_json(uid)})


@api
async def a_name_check(request):
    """Свободно ли имя: {ok, name} или {ok:false, msg}. kind=user|group|pack, id — чьё имя проверяем (чтобы своё не считалось занятым)."""
    import forum_names
    kind = request.query.get("kind")
    if kind not in forum_names.KINDS:
        raise FErr(400, "bad_kind", "Неверный тип")
    ref = request["fuid"] if kind == "user" else to_int(request.query.get("id"))
    name = forum_names.clean(request.query.get("name"))
    err = forum_names.valid(name) or await forum_names.taken_error(name, kind, ref)
    return J({"ok": not err, "name": name, "msg": err or ""})


@api
async def a_resolve(request):
    """exg/имя, @имя, +приглашение или полная ссылка → что это за объект и как его открыть."""
    import forum_names
    r = await forum_names.resolve(request.query.get("name"))
    if not r:
        raise FErr(404, "not_found", "Ссылка не найдена")
    me = request["fuid"]
    if r["kind"] == "group":
        r["member"] = bool(await P().fetchval("SELECT 1 FROM forum_group_members WHERE group_id=$1 AND user_id=$2", r["id"], me))
        r["public"] = bool(await P().fetchval("SELECT is_public FROM forum_groups WHERE id=$1", r["id"]))
    return J(r)


async def exg_redirect(request):
    """Короткая ссылка из браузера: /exg/имя → приложение форума, экран «открыть по ссылке»."""
    from urllib.parse import quote
    raise web.HTTPFound("/forum#/n/" + quote(request.match_info["name"], safe="+_"))


async def _read_image(request, field):
    form = await request.post()
    f = form.get(field)
    if f is None or not hasattr(f, "file"):
        raise FErr(400, "no_file", "Файл не выбран")
    data = f.file.read()
    mime = getattr(f, "content_type", "") or ""
    if not data or len(data) > IMG_MAX or mime not in IMG_MIMES:
        raise FErr(400, "bad_image", "Нужна картинка до 4 МБ (JPEG, PNG, WebP)")
    return data, mime


@api
async def a_me_avatar(request):
    data, mime = await _read_image(request, "file")
    await P().execute("UPDATE users SET avatar_data=$2,avatar_mime=$3 WHERE user_id=$1", request["fuid"], data, mime)
    return J({"ok": True})


@api
async def a_me_banner(request):
    form = await request.post()
    f = form.get("file")
    if f is None or not hasattr(f, "file"):
        raise FErr(400, "no_file", "Файл не выбран")
    try:   # картинка (до 4 МБ) или видео MP4/WebM (до 8 МБ) — тип определяется по содержимому
        data, mime = bm.banner_media(f.file.read(), getattr(f, "content_type", "") or "", img_max=IMG_MAX)
    except bm.ApiError:
        raise FErr(400, "bad_image", "Нужна картинка до 4 МБ (JPEG, PNG, WebP) или видео MP4/WebM до 8 МБ")
    await P().execute("UPDATE users SET banner_data=$2,banner_mime=$3 WHERE user_id=$1", request["fuid"], data, mime)
    return J({"ok": True})


async def a_avatar(request):
    uid = to_int(request.match_info.get("uid"))
    r = await P().fetchrow("SELECT avatar_data,avatar_mime,tg_avatar_data,photo_url FROM users WHERE user_id=$1", uid)
    hdr = {"Cache-Control": "public, max-age=300"}
    if r and r["avatar_data"]:
        return web.Response(body=bytes(r["avatar_data"]), content_type=r["avatar_mime"] or "image/jpeg", headers=hdr)
    if r and r["tg_avatar_data"]:
        return web.Response(body=bytes(r["tg_avatar_data"]), content_type="image/jpeg", headers=hdr)
    if r and r["photo_url"]:
        raise web.HTTPFound(r["photo_url"])
    raise web.HTTPNotFound()


def _ranged(request, data, mime, headers):
    """Ответ с поддержкой Range — без него Safari/iOS не проигрывают <video>."""
    h = dict(headers, **{"Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff"})
    size = len(data)
    m = re.match(r"bytes=(\d*)-(\d*)$", (request.headers.get("Range") or "").strip()) if mime.startswith("video/") else None
    if m and (m.group(1) or m.group(2)):
        a, b = m.groups()
        start, end = (max(size - int(b), 0), size - 1) if not a else (int(a), min(int(b), size - 1) if b else size - 1)
        if start > end or start >= size:
            return web.Response(status=416, headers={"Content-Range": "bytes */%d" % size})
        h["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
        return web.Response(status=206, body=data[start:end + 1], content_type=mime, headers=h)
    return web.Response(body=data, content_type=mime, headers=h)


async def a_banner(request):
    uid = to_int(request.match_info.get("uid"))
    r = await P().fetchrow("SELECT banner_data,banner_mime FROM users WHERE user_id=$1", uid)
    if not r or not r["banner_data"]:
        raise web.HTTPNotFound()
    return _ranged(request, bytes(r["banner_data"]), r["banner_mime"] or "image/jpeg", {"Cache-Control": "public, max-age=300"})


async def a_img(request):
    r = await P().fetchrow("SELECT data,mime FROM forum_images WHERE id=$1", to_int(request.match_info.get("iid")))
    if not r:
        raise web.HTTPNotFound()
    return _ranged(request, bytes(r["data"]), r["mime"], {"Cache-Control": "public, max-age=31536000, immutable"})


@api
async def a_user(request):
    me = request["fuid"]
    uid = to_int(request.query.get("id")) or me
    u = (await users_map([uid])).get(uid)
    if not u:
        raise FErr(404, "not_found", "Пользователь не найден")
    st = await P().fetchrow(
        "SELECT (SELECT count(*) FROM forum_posts WHERE user_id=$1 AND NOT deleted)::int posts,"
        "(SELECT count(*) FROM forum_follows WHERE followee_id=$1)::int followers,"
        "(SELECT count(*) FROM forum_follows WHERE follower_id=$1)::int following,"
        "EXISTS(SELECT 1 FROM forum_follows WHERE follower_id=$2 AND followee_id=$1) is_following,"
        "(SELECT created_at FROM users WHERE user_id=$1) joined", uid, me)
    return J({"user": dict(u), "posts": st["posts"], "followers": st["followers"], "following": st["following"],
              "is_following": st["is_following"], "joined": st["joined"].timestamp() if st["joined"] else None, "me": uid == me})


@api
async def a_follow(request):
    me = request["fuid"]
    d = await jbody(request)
    target = to_int(d.get("user_id"))
    if not target or target == me or not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1", target):
        raise FErr(400, "bad_user")
    ins = await P().fetchval("INSERT INTO forum_follows(follower_id,followee_id) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING 1", me, target)
    if ins:
        await notify(target, "follow", me)
    else:
        await P().execute("DELETE FROM forum_follows WHERE follower_id=$1 AND followee_id=$2", me, target)
    n = await P().fetchval("SELECT count(*) FROM forum_follows WHERE followee_id=$1", target)
    return J({"following": bool(ins), "followers": n})


@api
async def a_user_list(request):
    uid = to_int(request.query.get("id"))
    kind = request.query.get("kind")
    if kind == "following":
        rows = await P().fetch("SELECT followee_id u FROM forum_follows WHERE follower_id=$1 ORDER BY created_at DESC LIMIT 200", uid)
    else:
        rows = await P().fetch("SELECT follower_id u FROM forum_follows WHERE followee_id=$1 ORDER BY created_at DESC LIMIT 200", uid)
    um = await users_map([r["u"] for r in rows])
    return J({"users": [um[r["u"]] for r in rows if r["u"] in um]})


# ============================================================================ уведомления
NGROUP = {"like_p": "likes", "like_c": "likes", "comment": "comments", "reply": "comments", "mention": "mentions", "follow": "follows",
          "gmention": "mentions", "greply": "mentions"}
PREF_KEYS = ("likes", "comments", "mentions", "follows", "dms", "tg")


async def get_prefs(uid):
    """Настройки уведомлений пользователя (по умолчанию всё включено)."""
    r = await P().fetchrow("SELECT likes,comments,mentions,follows,dms,tg FROM forum_notif_prefs WHERE user_id=$1", uid)
    return {k: (bool(r[k]) if r else True) for k in PREF_KEYS}


async def notify(to, kind, actor, post_id=None, comment_id=None, group_id=None, msg_id=None):
    if not to or to == actor:
        return
    pr = await get_prefs(to)
    if not pr.get(NGROUP.get(kind, ""), True):
        return                                   # этот тип уведомлений пользователь отключил
    if kind in ("like_p", "like_c", "follow"):
        dup = await P().fetchval(
            "SELECT 1 FROM forum_notifs WHERE user_id=$1 AND kind=$2 AND actor_id=$3 AND post_id IS NOT DISTINCT FROM $4 AND comment_id IS NOT DISTINCT FROM $5",
            to, kind, actor, post_id, comment_id)
        if dup:
            return
    await P().execute("INSERT INTO forum_notifs(user_id,kind,actor_id,post_id,comment_id,group_id,msg_id) VALUES($1,$2,$3,$4,$5,$6,$7)",
                      to, kind, actor, post_id, comment_id, group_id, msg_id)
    # дублирование в Telegram: работает и когда приложение закрыто (лайки в Telegram не шлём — слишком шумно)
    if kind in ("comment", "reply", "mention", "follow", "gmention", "greply") and pr["tg"] and bm._BOT and _base() and bm.rate_ok(("forum_push", to, kind), 120):
        try:
            who = await bm.user_name(actor)
            what = {"comment": "прокомментировал(а) ваш пост", "reply": "ответил(а) на ваш комментарий", "mention": "упомянул(а) вас",
                    "follow": "подписался(лась) на вас", "gmention": "упомянул(а) вас в чате", "greply": "ответил(а) вам в чате"}[kind]
            if group_id:
                gt = await P().fetchval("SELECT title FROM forum_groups WHERE id=$1", group_id)
                what += " «%s»" % bm.esc((gt or "")[:40])
            link = (f"{_base()}/forum#/g/{group_id}" if group_id else
                    f"{_base()}/forum#/p/{post_id}" if post_id else f"{_base()}/forum#/u/{actor}")
            # адрес сервера не пишем в тексте — только кнопка «Открыть»
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть", web_app=WebAppInfo(url=link))]]) if link.startswith("https://") else None
            await bm._BOT.send_message(to, f"💬 <b>KMBP FORUM</b>\n{bm.esc(who)} {what}.", reply_markup=kb)
        except Exception:
            pass


async def mentions(text, actor, post_id, comment_id=None):
    names = list({m.lower() for m in re.findall(r"@([A-Za-z0-9_]{4,32})", text or "")})[:5]
    if not names:
        return set()
    rows = await P().fetch(
        "SELECT user_id FROM users WHERE lower(username)=ANY($1::text[]) UNION SELECT ref FROM forum_names WHERE kind='user' AND name=ANY($1::text[])", names)
    got = set()
    for r in rows:
        if r["user_id"] != actor:
            got.add(r["user_id"])
            await notify(r["user_id"], "mention", actor, post_id, comment_id)
    return got


@api
async def a_notifs(request):
    uid = request["fuid"]
    rows = await P().fetch(
        "SELECT n.id,n.kind,n.actor_id,n.post_id,n.comment_id,n.group_id,n.created_at,n.read,"
        "COALESCE(left(p.title || CASE WHEN p.title='' THEN p.body ELSE '' END, 80), (SELECT g.title FROM forum_groups g WHERE g.id=n.group_id)) snippet "
        "FROM forum_notifs n LEFT JOIN forum_posts p ON p.id=n.post_id WHERE n.user_id=$1 ORDER BY n.id DESC LIMIT 60", uid)
    um = await users_map([r["actor_id"] for r in rows])
    return J({"items": [{"id": r["id"], "kind": r["kind"], "actor": um.get(r["actor_id"]) or ghost(r["actor_id"]), "post_id": r["post_id"], "group_id": r["group_id"],
                         "comment_id": r["comment_id"], "ts": r["created_at"].timestamp(), "read": r["read"], "snippet": r["snippet"] or ""} for r in rows]})


@api
async def a_notifs_read(request):
    await P().execute("UPDATE forum_notifs SET read=TRUE WHERE user_id=$1 AND NOT read", request["fuid"])
    return J({"ok": True})


@api
async def a_notif_prefs(request):
    return J(await get_prefs(request["fuid"]))


@api
async def a_notif_prefs_set(request):
    uid = request["fuid"]
    d = await jbody(request)
    cur = await get_prefs(uid)
    for k in PREF_KEYS:
        if k in d:
            cur[k] = bool(d[k])
    await P().execute(
        "INSERT INTO forum_notif_prefs(user_id,likes,comments,mentions,follows,dms,tg) VALUES($1,$2,$3,$4,$5,$6,$7) "
        "ON CONFLICT (user_id) DO UPDATE SET likes=$2,comments=$3,mentions=$4,follows=$5,dms=$6,tg=$7", uid, *[cur[k] for k in PREF_KEYS])
    return J(cur)


@api
async def a_ping(request):
    uid = request["fuid"]
    n = await P().fetchval("SELECT count(*) FROM forum_notifs WHERE user_id=$1 AND NOT read", uid)
    from support import ensure_chat
    await ensure_chat(uid)
    m = await P().fetchval(
        "SELECT count(*) FROM direct_messages WHERE recipient_id=$1 AND read_at IS NULL AND NOT EXISTS(SELECT 1 FROM dm_hidden h WHERE h.user_id=$1 AND h.msg_id=direct_messages.id) "
        "AND NOT EXISTS(SELECT 1 FROM forum_chat_prefs p WHERE p.user_id=$1 AND p.peer_id=direct_messages.sender_id AND p.muted)", uid)
    import forum_groups
    gn, gtop = await forum_groups.unread_summary(uid)
    m += gn
    out = {"notifs": n, "msgs": m, "last": await P().fetchval("SELECT COALESCE(max(id),0) FROM forum_notifs WHERE user_id=$1", uid), "new": [], "dm": None}
    after = request.query.get("after")
    if after is not None and after.lstrip("-").isdigit():     # новые непрочитанные с момента прошлой проверки — для баннера/звука на устройстве
        rows = await P().fetch(
            "SELECT n.id,n.kind,n.actor_id,n.post_id,n.group_id,left(p.title || CASE WHEN p.title='' THEN p.body ELSE '' END, 80) snippet "
            "FROM forum_notifs n LEFT JOIN forum_posts p ON p.id=n.post_id WHERE n.user_id=$1 AND NOT n.read AND n.id>$2 ORDER BY n.id DESC LIMIT 5", uid, int(after))
        um = await users_map([r["actor_id"] for r in rows])
        out["new"] = [{"id": r["id"], "kind": r["kind"], "actor": (um.get(r["actor_id"]) or ghost(r["actor_id"]))["name"], "actor_id": r["actor_id"],
                       "post_id": r["post_id"], "group_id": r["group_id"], "snippet": r["snippet"] or ""} for r in rows]
    if m and (await get_prefs(uid))["dms"]:
        sid = await P().fetchval("SELECT sender_id FROM direct_messages WHERE recipient_id=$1 AND read_at IS NULL "
            "AND NOT EXISTS(SELECT 1 FROM forum_chat_prefs p WHERE p.user_id=$1 AND p.peer_id=direct_messages.sender_id AND p.muted) ORDER BY id DESC LIMIT 1", uid)
        if sid:
            sm = (await users_map([sid])).get(sid) or ghost(sid)
            out["dm"] = {"id": sid, "name": sm["name"]}
    if out["dm"] is None and gtop and (await get_prefs(uid))["dms"]:
        out["dm"] = gtop
    return J(out)


# ============================================================================ посты
POST_SQL = """SELECT p.id,p.user_id,p.board_id,p.title,p.body,p.created_at,p.edited_at,p.pinned,p.views,
  (SELECT count(*) FROM forum_likes l WHERE l.kind='p' AND l.target_id=p.id)::int likes,
  (SELECT count(*) FROM forum_comments c WHERE c.post_id=p.id AND NOT c.deleted)::int comments,
  EXISTS(SELECT 1 FROM forum_likes l WHERE l.kind='p' AND l.target_id=p.id AND l.user_id=$1) liked,
  EXISTS(SELECT 1 FROM forum_bookmarks b WHERE b.post_id=p.id AND b.user_id=$1) saved,
  ARRAY(SELECT i.id FROM forum_images i WHERE i.post_id=p.id AND i.mime LIKE 'image/%' ORDER BY i.id) imgs
  FROM forum_posts p"""


async def posts_json(rows, viewer, staff=False):
    um = await users_map([r["user_id"] for r in rows])
    boards = {b["id"]: b for b in await P().fetch("SELECT id,name,emoji FROM forum_boards")}
    media = {}
    if rows:
        for m in await P().fetch("SELECT id,post_id,mime,octet_length(data) sz FROM forum_images WHERE post_id=ANY($1::int[]) ORDER BY id", [r["id"] for r in rows]):
            media.setdefault(m["post_id"], []).append({"id": m["id"], "k": "video" if m["mime"].startswith("video/") else "image", "size": m["sz"]})
    out = []
    for r in rows:
        b = boards.get(r["board_id"])
        out.append({"id": r["id"], "user": um.get(r["user_id"]) or ghost(r["user_id"]), "board": ({"id": b["id"], "name": b["name"], "emoji": b["emoji"]} if b else None),
                    "title": r["title"], "body": r["body"], "ts": r["created_at"].timestamp(), "edited": r["edited_at"] is not None, "pinned": r["pinned"],
                    "views": r["views"], "likes": r["likes"], "comments": r["comments"], "liked": r["liked"], "saved": r["saved"],
                    "imgs": list(r["imgs"] or []), "media": media.get(r["id"], []), "mine": r["user_id"] == viewer, "can_edit": r["user_id"] == viewer or staff})
    return out


@api
async def a_feed(request):
    me = request["fuid"]
    q = request.query
    tab = q.get("tab") or "all"
    board = to_int(q.get("board"))
    user = to_int(q.get("user"))
    off = max(0, to_int(q.get("offset")))
    limit = 20
    args = [me]
    where = ["NOT p.deleted"]

    def add(cond, val):
        args.append(val)
        where.append(cond.replace("?", f"${len(args)}"))
    if board:
        add("p.board_id=?", board)
    if user:
        add("p.user_id=?", user)
    order = "p.pinned DESC, p.id DESC" if (board or tab == "all") and not user else "p.id DESC"
    if tab == "follow":
        where.append("p.user_id IN (SELECT followee_id FROM forum_follows WHERE follower_id=$1)")
    elif tab == "saved":
        where.append("EXISTS(SELECT 1 FROM forum_bookmarks b WHERE b.post_id=p.id AND b.user_id=$1)")
        order = "p.id DESC"
    elif tab == "top":
        where.append("p.created_at > now() - interval '30 days'")
        order = ("((SELECT count(*) FROM forum_likes l WHERE l.kind='p' AND l.target_id=p.id)*2 + (SELECT count(*) FROM forum_comments c WHERE c.post_id=p.id AND NOT c.deleted)*3 + p.views/25.0) DESC, p.id DESC")
    sql = f"{POST_SQL} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT {limit} OFFSET {off}"
    rows = await P().fetch(sql, *args)
    return J({"posts": await posts_json(rows, me, await is_staff(me)), "more": len(rows) == limit})


@api
async def a_post_get(request):
    me = request["fuid"]
    pid = to_int(request.query.get("id"))
    r = await P().fetchrow(f"{POST_SQL} WHERE p.id=$2 AND NOT p.deleted", me, pid)
    if not r:
        raise FErr(404, "not_found", "Пост не найден или удалён")
    staff = await is_staff(me)
    if r["user_id"] != me and (me, pid) not in _seen_views:
        _seen_views[(me, pid)] = 1
        if len(_seen_views) > 20000:
            _seen_views.clear()
        await P().execute("UPDATE forum_posts SET views=views+1 WHERE id=$1", pid)
    post = (await posts_json([r], me, staff))[0]
    crow = await P().fetch(
        "SELECT c.id,c.user_id,c.parent_id,c.body,c.created_at,c.edited_at,c.deleted,"
        "(SELECT count(*) FROM forum_likes l WHERE l.kind='c' AND l.target_id=c.id)::int likes,"
        "EXISTS(SELECT 1 FROM forum_likes l WHERE l.kind='c' AND l.target_id=c.id AND l.user_id=$2) liked "
        "FROM forum_comments c WHERE c.post_id=$1 ORDER BY c.id LIMIT 600", pid, me)
    um = await users_map([c["user_id"] for c in crow])
    comments = [{"id": c["id"], "user": um.get(c["user_id"]) or ghost(c["user_id"]), "parent": c["parent_id"], "body": "" if c["deleted"] else c["body"],
                 "deleted": c["deleted"], "ts": c["created_at"].timestamp(), "likes": c["likes"], "liked": c["liked"],
                 "mine": c["user_id"] == me, "can_delete": c["user_id"] == me or staff,
                 "edited": c["edited_at"] is not None and not c["deleted"], "can_edit": c["user_id"] == me and not c["deleted"]} for c in crow]
    return J({"post": post, "comments": comments})


def _sniff_media(data, mime):
    """Тип определяем по содержимому, а не по заголовку клиента. -> (mime, is_video) или None."""
    if data[4:8] == b"ftyp" and data[8:12] not in _VIDEO_BAD_BRANDS:
        return "video/mp4", True                      # MP4 / MOV (H.264)
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm", True                     # WebM
    if mime in IMG_MIMES:
        return mime, False
    return None


async def _images_from_form(form, already=0, already_bytes=0):
    """Файлы поста (поле img): фото и видео. already / already_bytes — сколько медиа уже есть у поста (при правке)."""
    files, total = [], already_bytes
    for f in form.getall("img", []):
        if not hasattr(f, "file"):
            continue
        data = f.file.read()
        if not data:
            continue
        kind = _sniff_media(data, getattr(f, "content_type", "") or "")
        if not kind:
            raise FErr(400, "bad_image", "Фото: JPEG/PNG/WebP/GIF до 4 МБ, видео: MP4/WebM до 20 МБ")
        mime, is_vid = kind
        if len(data) > (VID_MAX if is_vid else IMG_MAX):
            raise FErr(400, "bad_video" if is_vid else "bad_image",
                       "Видео больше 20 МБ — обрежьте длину в редакторе" if is_vid else "Фото больше 4 МБ")
        total += len(data)
        files.append((data, mime))
    if len(files) + already > MEDIA_COUNT:
        raise FErr(400, "too_many_images", f"В посте не больше {MEDIA_COUNT} фото и видео")
    if total > MEDIA_TOTAL:
        raise FErr(400, "media_too_big", f"Все вложения поста вместе — не больше {MEDIA_TOTAL // 1048576} МБ")
    return files


@api
async def a_post_create(request):
    me = request["fuid"]
    if not bm.rate_ok(("fpost", me), 12):
        raise FErr(429, "too_fast", "Не так быстро — подождите несколько секунд")
    form = await request.clone(client_max_size=POST_BODY_MAX).post()
    title = str(form.get("title") or "").strip()[:TITLE_MAX]
    body = str(form.get("body") or "").strip()[:BODY_MAX]
    board = to_int(form.get("board_id")) or None
    files = await _images_from_form(form)
    if not body and not files:
        raise FErr(400, "empty", "Напишите текст или добавьте фото или видео")
    if board:
        b = await P().fetchrow("SELECT admin_only FROM forum_boards WHERE id=$1", board)
        if not b:
            raise FErr(400, "bad_board", "Раздел не найден")
        if b["admin_only"] and not await is_staff(me):
            raise FErr(403, "board_locked", "В этот раздел пишут только админы")
    pid = await P().fetchval("INSERT INTO forum_posts(user_id,board_id,title,body) VALUES($1,$2,$3,$4) RETURNING id", me, board, title, body)
    for data, mime in files:
        await P().execute("INSERT INTO forum_images(post_id,data,mime) VALUES($1,$2,$3)", pid, data, mime)
    await mentions(f"{title}\n{body}", me, pid)
    return J({"ok": True, "id": pid})


async def _own_post(me, pid):
    r = await P().fetchrow("SELECT user_id FROM forum_posts WHERE id=$1 AND NOT deleted", pid)
    if not r:
        raise FErr(404, "not_found", "Пост не найден")
    if r["user_id"] != me and not await is_staff(me):
        raise FErr(403, "forbidden", "Нет прав")
    return r


@api
async def a_post_edit(request):
    """Правка поста. JSON {id,title,body} — только текст; multipart (id,title,body,remove=1,2,3 + img-файлы) — ещё и медиа."""
    me = request["fuid"]
    if (request.content_type or "").startswith("multipart/"):
        d = await request.clone(client_max_size=POST_BODY_MAX).post()
        remove = [to_int(x) for x in str(d.get("remove") or "").split(",") if x.strip()]
        multipart = True
    else:
        d, remove, multipart = await jbody(request), [], False
    pid = to_int(d.get("id"))
    await _own_post(me, pid)
    title = str(d.get("title") or "").strip()[:TITLE_MAX]
    body = str(d.get("body") or "").strip()[:BODY_MAX]
    # сначала проверяем всё, и только потом удаляем/вставляем — при ошибке пост остаётся как был
    cnt, sz = await P().fetchrow("SELECT count(*)::int, coalesce(sum(octet_length(data)),0)::bigint FROM forum_images WHERE post_id=$1 AND NOT (id=ANY($2::int[]))", pid, remove)
    files = await _images_from_form(d, cnt, sz) if multipart else []
    if not body and not files and not cnt:
        raise FErr(400, "empty", "Пост не может быть пустым")
    if remove:
        await P().execute("DELETE FROM forum_images WHERE post_id=$1 AND id=ANY($2::int[])", pid, remove)
    await P().execute("UPDATE forum_posts SET title=$2,body=$3,edited_at=now() WHERE id=$1", pid, title, body)
    for data, mime in files:
        await P().execute("INSERT INTO forum_images(post_id,data,mime) VALUES($1,$2,$3)", pid, data, mime)
    return J({"ok": True})


@api
async def a_post_delete(request):
    me = request["fuid"]
    pid = to_int((await jbody(request)).get("id"))
    await _own_post(me, pid)
    await P().execute("UPDATE forum_posts SET deleted=TRUE, pinned=FALSE WHERE id=$1", pid)
    return J({"ok": True})


@api
async def a_post_pin(request):
    me = request["fuid"]
    if not await is_staff(me):
        raise FErr(403, "forbidden", "Только для админов")
    d = await jbody(request)
    await P().execute("UPDATE forum_posts SET pinned=$2 WHERE id=$1", to_int(d.get("id")), bool(d.get("pin", True)))
    return J({"ok": True})


@api
async def a_like(request):
    me = request["fuid"]
    d = await jbody(request)
    kind, tid = ("c" if d.get("kind") == "c" else "p"), to_int(d.get("id"))
    if kind == "p":
        t = await P().fetchrow("SELECT user_id,id post_id FROM forum_posts WHERE id=$1 AND NOT deleted", tid)
    else:
        t = await P().fetchrow("SELECT user_id,post_id FROM forum_comments WHERE id=$1 AND NOT deleted", tid)
    if not t:
        raise FErr(404, "not_found")
    ins = await P().fetchval("INSERT INTO forum_likes(user_id,kind,target_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING 1", me, kind, tid)
    if ins:
        await notify(t["user_id"], "like_" + kind, me, t["post_id"], tid if kind == "c" else None)
    else:
        await P().execute("DELETE FROM forum_likes WHERE user_id=$1 AND kind=$2 AND target_id=$3", me, kind, tid)
    n = await P().fetchval("SELECT count(*) FROM forum_likes WHERE kind=$1 AND target_id=$2", kind, tid)
    return J({"liked": bool(ins), "count": n})


@api
async def a_bookmark(request):
    me = request["fuid"]
    pid = to_int((await jbody(request)).get("post_id"))
    if not await P().fetchval("SELECT 1 FROM forum_posts WHERE id=$1 AND NOT deleted", pid):
        raise FErr(404, "not_found")
    ins = await P().fetchval("INSERT INTO forum_bookmarks(user_id,post_id) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING 1", me, pid)
    if not ins:
        await P().execute("DELETE FROM forum_bookmarks WHERE user_id=$1 AND post_id=$2", me, pid)
    return J({"saved": bool(ins)})


@api
async def a_comment(request):
    me = request["fuid"]
    if not bm.rate_ok(("fcom", me), 3):
        raise FErr(429, "too_fast", "Не так быстро")
    d = await jbody(request)
    pid = to_int(d.get("post_id"))
    body = str(d.get("body") or "").strip()[:COMMENT_MAX]
    if not body:
        raise FErr(400, "empty", "Пустой комментарий")
    post = await P().fetchrow("SELECT user_id FROM forum_posts WHERE id=$1 AND NOT deleted", pid)
    if not post:
        raise FErr(404, "not_found", "Пост не найден")
    parent = to_int(d.get("parent_id")) or None
    par = None
    if parent:
        par = await P().fetchrow("SELECT user_id,parent_id FROM forum_comments WHERE id=$1 AND post_id=$2", parent, pid)
        if not par:
            parent = None
        elif par["parent_id"]:
            parent = par["parent_id"]    # глубже одного уровня не вкладываем — ответ уходит в ветку верхнего комментария
    cid = await P().fetchval("INSERT INTO forum_comments(post_id,user_id,parent_id,body) VALUES($1,$2,$3,$4) RETURNING id", pid, me, parent, body)
    got = await mentions(body, me, pid, cid)
    if par and par["user_id"] != me and par["user_id"] not in got:
        await notify(par["user_id"], "reply", me, pid, cid)
    if post["user_id"] != me and post["user_id"] not in got and not (par and par["user_id"] == post["user_id"]):
        await notify(post["user_id"], "comment", me, pid, cid)
    return J({"ok": True, "id": cid})


@api
async def a_comment_edit(request):
    """Редактирование своего комментария. Ставит edited_at → в ленте «изм.»."""
    me = request["fuid"]
    if not bm.rate_ok(("fcomedit", me), 2):
        raise FErr(429, "too_fast", "Не так быстро")
    d = await jbody(request)
    cid = to_int(d.get("id"))
    body = str(d.get("body") or "").strip()[:COMMENT_MAX]
    if not body:
        raise FErr(400, "empty", "Пустой комментарий")
    r = await P().fetchrow("SELECT user_id,post_id,body FROM forum_comments WHERE id=$1 AND NOT deleted", cid)
    if not r:
        raise FErr(404, "not_found", "Комментарий не найден или удалён")
    if r["user_id"] != me:
        raise FErr(403, "forbidden", "Можно изменять только свои комментарии")
    if body != r["body"]:
        await P().execute("UPDATE forum_comments SET body=$2,edited_at=now() WHERE id=$1", cid, body)
        _m = lambda t: {m.lower() for m in re.findall(r"@([A-Za-z0-9_]{4,32})", t or "")}
        fresh = _m(body) - _m(r["body"])               # уведомляем только о НОВЫХ упоминаниях, чтобы не спамить повторно
        if fresh:
            await mentions(" ".join("@" + n for n in fresh), me, r["post_id"], cid)
    return J({"ok": True, "edited": body != r["body"]})


@api
async def a_comment_delete(request):
    me = request["fuid"]
    cid = to_int((await jbody(request)).get("id"))
    r = await P().fetchrow("SELECT user_id FROM forum_comments WHERE id=$1", cid)
    if not r:
        raise FErr(404, "not_found")
    if r["user_id"] != me and not await is_staff(me):
        raise FErr(403, "forbidden")
    await P().execute("UPDATE forum_comments SET deleted=TRUE WHERE id=$1", cid)
    return J({"ok": True})


@api
async def a_report(request):
    me = request["fuid"]
    d = await jbody(request)
    kind, tid = ("c" if d.get("kind") == "c" else "p"), to_int(d.get("id"))
    reason = str(d.get("reason") or "").strip()[:300]
    await P().execute("INSERT INTO forum_reports(reporter_id,kind,target_id,reason) VALUES($1,$2,$3,$4)", me, kind, tid, reason)
    mod = await bm.get_setting("mod_chat")
    if mod and bm._BOT:
        try:
            who = await bm.user_name(me)
            link = f"{_base()}/forum#/post/{tid}" if kind == "p" else ""
            await bm._BOT.send_message(int(mod), f"🚩 <b>Жалоба на {'пост' if kind == 'p' else 'комментарий'} #{tid}</b> (KMBP FORUM)\nОт: {bm.esc(who)} (<code>{me}</code>)\n"
                                                 f"Причина: {bm.esc(reason) or '—'}\n{link}")
        except Exception:
            log.warning("forum report notify failed")
    return J({"ok": True})


# ============================================================================ разделы (для админов)
@api
async def a_board_save(request):
    me = request["fuid"]
    if not await bm.is_main(me):
        raise FErr(403, "forbidden", "Только главные админы")
    d = await jbody(request)
    name = str(d.get("name") or "").strip()[:40]
    emoji = str(d.get("emoji") or "💬").strip()[:8] or "💬"
    if not name:
        raise FErr(400, "empty", "Название раздела")
    bid = to_int(d.get("id"))
    if bid:
        await P().execute("UPDATE forum_boards SET name=$2,emoji=$3,admin_only=$4 WHERE id=$1", bid, name, emoji, bool(d.get("admin_only")))
    else:
        await P().execute("INSERT INTO forum_boards(name,emoji,sort,admin_only) VALUES($1,$2,(SELECT coalesce(max(sort),0)+1 FROM forum_boards),$3)", name, emoji, bool(d.get("admin_only")))
    return J({"ok": True})


@api
async def a_board_delete(request):
    if not await bm.is_main(request["fuid"]):
        raise FErr(403, "forbidden", "Только главные админы")
    await P().execute("DELETE FROM forum_boards WHERE id=$1", to_int((await jbody(request)).get("id")))
    return J({"ok": True})


# ============================================================================ поиск
def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@api
async def a_search(request):
    me = request["fuid"]
    q = (request.query.get("q") or "").strip()[:60]
    if len(q) < 2:
        return J({"posts": [], "users": []})
    rows = await P().fetch(f"{POST_SQL} WHERE NOT p.deleted AND (p.title ILIKE $2 OR p.body ILIKE $2) ORDER BY p.id DESC LIMIT 30", me, _like(q))
    ur = await P().fetch(
        "SELECT u.user_id FROM users u LEFT JOIN forum_names fn ON fn.kind='user' AND fn.ref=u.user_id "
        "WHERE u.user_id>0 AND (u.username ILIKE $1 OR fn.name ILIKE $1 OR u.first_name ILIKE $1 OR u.last_name ILIKE $1) ORDER BY u.last_seen DESC NULLS LAST LIMIT 20", _like(q.lstrip("@")))
    um = await users_map([r["user_id"] for r in ur])
    gr = await P().fetch(
        "SELECT g.id,g.kind,g.title,g.descr,g.board_id,(g.avatar_data IS NOT NULL) av,(SELECT count(*) FROM forum_group_members x WHERE x.group_id=g.id)::int n "
        "FROM forum_groups g WHERE g.is_public AND NOT g.deleted AND (g.title ILIKE $1 OR g.descr ILIKE $1 OR g.id IN "
        "(SELECT ref FROM forum_names WHERE kind='group' AND name ILIKE $1)) ORDER BY n DESC LIMIT 10", _like(q.lstrip("@")))
    import forum_groups
    mine = {r["group_id"] for r in await P().fetch("SELECT group_id FROM forum_group_members WHERE user_id=$1", me)}
    return J({"posts": await posts_json(rows, me, await is_staff(me)), "users": [um[r["user_id"]] for r in ur if r["user_id"] in um],
              "groups": await forum_groups._items(gr, mine)})


# ============================================================================ личные сообщения (те же чаты, что в мини-аппе)
# ---- вложения в личных сообщениях: фото / видео / файлы ----
ATTACH_MAX = 20 * 1024 * 1024
VIDEO_MIMES = ("video/mp4", "video/webm", "video/quicktime")
_EXT_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif",
             "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}


def attach_info(fname, mime):
    """(вид, mime): вид — image / video / file. Тип берём из mime, а если браузер прислал пустой — из расширения."""
    m = str(mime or "").split(";")[0].strip().lower()
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
    if m in ("", "application/octet-stream") and ext in _EXT_MIME:
        m = _EXT_MIME[ext]
    if m == "video/x-m4v":
        m = "video/mp4"
    if m in bm.IMG_MIMES:
        return "image", m
    if m in VIDEO_MIMES:
        return "video", m
    return "file", "application/octet-stream"


EM_RE = re.compile(r":em(\d{1,9}):")


def strip_em(s):
    """Эмодзи из паков в тексте записаны токеном :em123: — в списках и пушах заменяем на обычный смайлик."""
    return EM_RE.sub("🙂", s or "")


def last_preview(r):
    """Подпись последнего сообщения в списке чатов."""
    if r["body"]:
        return strip_em(r["body"])
    if r["voice_dur"]:
        return "📹 Видеосообщение" if bm.note_mime(r["file_mime"]) else "🎤 Голосовое сообщение"
    if r["file_name"] or r["file_mime"]:
        k, _ = attach_info(r["file_name"] or "", r["file_mime"])
        return ("GIF" if r["file_mime"] == "image/gif" else "📷 Фото") if k == "image" else "🎬 Видео" if k == "video" else "📎 " + (r["file_name"] or "Файл")
    return ""


@api
async def a_chats(request):
    me = request["fuid"]
    from support import SUPPORT_ID, ensure_chat
    await ensure_chat(me)
    rows = await P().fetch(
        """SELECT DISTINCT ON (peer) peer,body,created_at,sender_id,read_at,file_name,voice_dur,file_mime FROM (
            SELECT CASE WHEN sender_id=$1 THEN recipient_id ELSE sender_id END peer,body,created_at,id,sender_id,read_at,file_name,voice_dur,file_mime
            FROM direct_messages WHERE (sender_id=$1 OR recipient_id=$1)
            AND NOT EXISTS(SELECT 1 FROM dm_hidden h WHERE h.user_id=$1 AND h.msg_id=direct_messages.id)) x
            ORDER BY peer,created_at DESC,id DESC LIMIT 150""", me)
    unread = {r["sender_id"]: r["c"] for r in await P().fetch(
        "SELECT sender_id,count(*)::int c FROM direct_messages WHERE recipient_id=$1 AND read_at IS NULL GROUP BY 1", me)}
    um = await users_map([r["peer"] for r in rows])
    prefs = {q["peer_id"]: q for q in await P().fetch("SELECT peer_id,pinned_at,muted,archived FROM forum_chat_prefs WHERE user_id=$1", me)}
    out = []
    for r in rows:
        if r["peer"] not in um:
            continue
        pf = prefs.get(r["peer"])
        n = unread.get(r["peer"], 0)
        muted = bool(pf and pf["muted"])
        # архив: новое входящее в чате не «без звука» возвращает его в список (как в Telegram)
        arch = bool(pf and pf["archived"]) and not (n and not muted) and r["peer"] != SUPPORT_ID
        out.append({"user": um[r["peer"]], "last": last_preview(r)[:120], "ts": r["created_at"].timestamp(),
                    "mine": r["sender_id"] == me, "unread": n, "support": r["peer"] == SUPPORT_ID,
                    "pin": pf["pinned_at"].timestamp() if pf and pf["pinned_at"] else 0, "muted": muted, "arch": arch})
    out.sort(key=lambda x: (not x["support"], -x["pin"], -x["ts"]))
    import forum_groups
    return J({"chats": out, "groups": await forum_groups.my_groups(me)})


MAX_PINNED_CHATS = 5


@api
async def a_chat_pref(request):
    """Закрепить / «без звука» / в архив для диалога. Передаются только меняемые поля: pinned, muted, archived (bool)."""
    me = request["fuid"]
    d = await jbody(request)
    peer = to_int(d.get("peer"))
    from support import SUPPORT_ID
    if not peer or peer == me or peer == SUPPORT_ID:
        raise FErr(400, "bad_peer", "Для этого чата это недоступно")
    if not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1", peer):
        raise FErr(404, "not_found", "Пользователь не найден")
    cur = await P().fetchrow("SELECT pinned_at,muted,archived FROM forum_chat_prefs WHERE user_id=$1 AND peer_id=$2", me, peer)
    pinned_at = cur["pinned_at"] if cur else None
    muted = bool(cur and cur["muted"])
    archived = bool(cur and cur["archived"])
    if "muted" in d:
        muted = bool(d["muted"])
    if "archived" in d:
        archived = bool(d["archived"])
        if archived:
            pinned_at = None
    if "pinned" in d:
        if d["pinned"]:
            if pinned_at is None:
                if await P().fetchval("SELECT count(*) FROM forum_chat_prefs WHERE user_id=$1 AND pinned_at IS NOT NULL", me) + \
                        await P().fetchval("SELECT count(*) FROM forum_group_members WHERE user_id=$1 AND pinned_at IS NOT NULL", me) >= MAX_PINNED_CHATS:
                    raise FErr(400, "too_many_pins", "Можно закрепить не больше %d чатов" % MAX_PINNED_CHATS)
                pinned_at = datetime.now(timezone.utc)
            archived = False
        else:
            pinned_at = None
    if pinned_at is None and not muted and not archived:
        await P().execute("DELETE FROM forum_chat_prefs WHERE user_id=$1 AND peer_id=$2", me, peer)
    else:
        await P().execute(
            """INSERT INTO forum_chat_prefs(user_id,peer_id,pinned_at,muted,archived) VALUES($1,$2,$3,$4,$5)
               ON CONFLICT(user_id,peer_id) DO UPDATE SET pinned_at=EXCLUDED.pinned_at, muted=EXCLUDED.muted, archived=EXCLUDED.archived""",
            me, peer, pinned_at, muted, archived)
    return J({"ok": True, "pin": pinned_at.timestamp() if pinned_at else 0, "muted": muted, "arch": archived})


@api
async def a_chats_search(request):
    """Поиск по тексту сообщений во всех личных чатах пользователя."""
    me = request["fuid"]
    q = (request.query.get("q") or "").strip()[:80]
    if len(q) < 2:
        return J({"results": []})
    like = _like(q)
    rows = await P().fetch(
        """SELECT id,sender_id,recipient_id,body,created_at FROM direct_messages
           WHERE (sender_id=$1 OR recipient_id=$1) AND body ILIKE $2
           AND NOT EXISTS(SELECT 1 FROM dm_hidden h WHERE h.user_id=$1 AND h.msg_id=direct_messages.id)
           ORDER BY id DESC LIMIT 40""", me, like)
    um = await users_map([r["recipient_id"] if r["sender_id"] == me else r["sender_id"] for r in rows])
    out = []
    ql = q.lower()
    for r in rows:
        peer = r["recipient_id"] if r["sender_id"] == me else r["sender_id"]
        if peer not in um:
            continue
        body = " ".join((r["body"] or "").split())
        i = max(body.lower().find(ql), 0)
        st = max(0, i - 35)
        out.append({"id": r["id"], "user": um[peer], "mine": r["sender_id"] == me, "ts": r["created_at"].timestamp(),
                    "text": ("…" if st else "") + body[st:st + 140]})
    import forum_groups
    out += await forum_groups.search_msgs(me, q, like)
    out.sort(key=lambda x: -x["ts"])
    return J({"results": out})


@api
async def a_messages(request):
    me = request["fuid"]
    peer = to_int(request.query.get("peer"))
    if not peer or peer == me:
        raise FErr(400, "bad_peer")
    bm._viewing[(me, peer)] = time.monotonic()
    await P().execute("UPDATE direct_messages SET read_at=now() WHERE recipient_id=$1 AND sender_id=$2 AND read_at IS NULL", me, peer)
    rows = await P().fetch(
        """SELECT * FROM (SELECT id,sender_id,body,created_at,read_at,file_name,file_mime,file_size,voice_dur,voice_wave,voice_heard,
            reply_to,edited_at,pinned_at,fwd_from,(file_data IS NOT NULL) has_file FROM direct_messages
            WHERE ((sender_id=$1 AND recipient_id=$2) OR (sender_id=$2 AND recipient_id=$1))
            AND NOT EXISTS(SELECT 1 FROM dm_hidden h WHERE h.user_id=$1 AND h.msg_id=direct_messages.id)
            ORDER BY id DESC LIMIT $3) q ORDER BY id""", me, peer, min(max(to_int(request.query.get("limit"), 120), 20), 1000))
    um = await users_map([peer])
    by_me, by_peer = await bm.block_state(me, peer)
    typing = time.monotonic() - bm._typing.get((peer, me, 0), 0) < 5
    recording = ("video" if time.monotonic() - bm._typing.get((peer, me, 2), 0) < 5
                 else "voice" if time.monotonic() - bm._typing.get((peer, me, 1), 0) < 5 else False)
    from support import SUPPORT_ID, mode_of
    extra = {"support_mode": await mode_of(me)} if peer == SUPPORT_ID else {}
    seen = await P().fetchval("SELECT last_seen FROM users WHERE user_id=$1", peer)
    online = bool(seen and (datetime.now(timezone.utc) - seen).total_seconds() < 90)
    # ответы: оригиналы могут лежать за пределами окна из 120 сообщений
    rids = list({r["reply_to"] for r in rows if r["reply_to"]})
    replies = {}
    if rids:
        for q in await P().fetch(
                """SELECT id,sender_id,body,file_name,file_mime,(file_data IS NOT NULL) has_file FROM direct_messages
                   WHERE id=ANY($1::bigint[]) AND ((sender_id=$2 AND recipient_id=$3) OR (sender_id=$3 AND recipient_id=$2))""", rids, me, peer):
            replies[q["id"]] = {"id": q["id"], "mine": q["sender_id"] == me,
                                "text": bm.dm_preview(q["body"], q["file_name"], q["file_mime"])[:120] or ("📎 Файл" if q["has_file"] else "")}
    fwd_names = {}
    fids = list({r["fwd_from"] for r in rows if r["fwd_from"]})
    if fids:
        for q in await P().fetch("SELECT user_id,username,first_name,last_name FROM users WHERE user_id=ANY($1::bigint[])", fids):
            fwd_names[q["user_id"]] = " ".join(x for x in [q["first_name"], q["last_name"]] if x) or q["username"] or "Пользователь"
    pins = [{"id": q["id"], "text": bm.dm_preview(q["body"], q["file_name"], q["file_mime"])[:120] or "Сообщение"} for q in await P().fetch(
        """SELECT id,body,file_name,file_mime FROM direct_messages
           WHERE pinned_at IS NOT NULL AND ((sender_id=$1 AND recipient_id=$2) OR (sender_id=$2 AND recipient_id=$1))
           AND NOT EXISTS(SELECT 1 FROM dm_hidden h WHERE h.user_id=$1 AND h.msg_id=direct_messages.id)
           ORDER BY pinned_at DESC LIMIT 20""", me, peer)]
    rx = {}
    if rows:
        for q in await P().fetch(
                "SELECT msg_id,emoji,count(*) n,bool_or(user_id=$2) mine FROM forum_msg_reactions WHERE msg_id=ANY($1::bigint[]) GROUP BY msg_id,emoji ORDER BY min(created_at)",
                [r["id"] for r in rows], me):
            rx.setdefault(q["msg_id"], []).append({"e": q["emoji"], "n": q["n"], "mine": q["mine"]})
    stk = {}
    if rows:
        stk = {q["msg_id"]: q["sticker_id"] for q in await P().fetch(
            "SELECT msg_id,sticker_id FROM forum_msg_stickers WHERE msg_id=ANY($1::bigint[])", [r["id"] for r in rows])}
    # ответы на посты ленты: карточка поста внутри пузыря (пост мог быть удалён)
    pposts = {}
    if rows:
        prs = await P().fetch(
            """SELECT mp.msg_id, mp.post_id, p.user_id, p.title, p.body, p.deleted,
               (SELECT i.id FROM forum_images i WHERE i.post_id=p.id AND i.mime LIKE 'image/%' ORDER BY i.id LIMIT 1) img
               FROM forum_msg_posts mp LEFT JOIN forum_posts p ON p.id=mp.post_id WHERE mp.msg_id=ANY($1::bigint[])""",
            [r["id"] for r in rows])
        pum = await users_map([q["user_id"] for q in prs if q["user_id"]]) if prs else {}
        for q in prs:
            if q["user_id"] is None or q["deleted"]:
                pposts[q["msg_id"]] = {"id": q["post_id"], "gone": True, "title": "", "text": "", "author": "", "img": None}
            else:
                pposts[q["msg_id"]] = {"id": q["post_id"], "gone": False, "title": (q["title"] or "")[:120],
                                       "text": " ".join((q["body"] or "").split())[:140],
                                       "author": (pum.get(q["user_id"]) or ghost(q["user_id"]))["name"], "img": q["img"]}
    def one(r):
        voice = note = None
        if r["voice_dur"] and r["has_file"]:
            if bm.note_mime(r["file_mime"]):
                note = {"url": bm.img_url("dm", r["id"]), "dur": r["voice_dur"], "heard": r["voice_heard"] is not None}
            else:
                voice = {"url": bm.img_url("dm", r["id"]), "dur": r["voice_dur"], "wave": r["voice_wave"] or "",
                         "heard": r["voice_heard"] is not None}
        att = None
        if r["has_file"] and not voice and not note:
            kind, _ = attach_info(r["file_name"] or "", r["file_mime"])
            att = {"url": bm.img_url("dm", r["id"]), "name": r["file_name"] or "Файл", "size": r["file_size"] or 0, "kind": kind}
            if r["file_mime"] == "image/gif":
                att["gif"] = True
        m = {"id": r["id"], "mine": r["sender_id"] == me, "body": r["body"] or "", "ts": r["created_at"].timestamp(), "read": r["read_at"] is not None,
             "rts": r["read_at"].timestamp() if r["read_at"] else None}
        if rx.get(r["id"]):
            m["rx"] = rx[r["id"]]
        if r["edited_at"] is not None:
            m["edited"] = True
        if r["pinned_at"] is not None:
            m["pinned"] = True
        if r["reply_to"]:
            m["reply"] = replies.get(r["reply_to"]) or {"id": r["reply_to"], "text": "Сообщение удалено", "gone": True}
        if r["fwd_from"]:
            m["fwd"] = fwd_names.get(r["fwd_from"], "Пользователь")
        if pposts.get(r["id"]):
            m["post"] = pposts[r["id"]]
        if stk.get(r["id"]):
            m["sticker"] = {"id": stk[r["id"]]}
        if att:
            m["file"] = att
        if voice:
            m["voice"] = voice
        if note:
            m["note"] = note
        return m
    return J({"peer": um.get(peer) or ghost(peer), "typing": typing, "recording": recording, "blocked": bool(by_me or by_peer),
              "blocked_by_me": bool(by_me), "online": online, "seen": seen.timestamp() if seen else None, "pins": pins, **extra,
              "messages": [one(r) for r in rows]})


@api
async def a_message_send(request):
    me = request["fuid"]
    fdata = fmime = fname = None
    if (request.content_type or "").startswith("multipart/"):
        form = await request.post()
        d = {k: form.get(k) for k in ("peer", "text", "reply_to", "post_id", "voice_dur", "voice_wave", "note_dur", "sticker_id", "gif")}
        f = form.get("file")
        if f is not None and hasattr(f, "file"):
            fdata = f.file.read() or None
            fmime = str(getattr(f, "content_type", "") or "")[:100]
            fname = (os.path.basename(str(getattr(f, "filename", "") or "")) or "file")[:120]
            is_rec = bool(d.get("voice_dur") or d.get("note_dur"))
            if fdata and len(fdata) > (bm.MAX_FILE if is_rec else ATTACH_MAX):
                raise FErr(400, "bad_size", "Запись слишком большая" if is_rec else "Файл слишком большой (до %d МБ)" % (ATTACH_MAX // 1048576))
    else:
        d = await jbody(request)
    peer = to_int(d.get("peer"))
    text = str(d.get("text") or "").strip()[:3000]
    if d.get("gif") and not fdata:              # GIF из «Моих GIF» (s<id>) или из поиска (g<id>) — уходит обычным вложением
        import forum_gifs
        fdata, fmime, fname = await forum_gifs.for_send(me, d.get("gif"))
    try:
        voice = bm.parse_voice(d, fdata, fmime)
        note = None if voice else bm.parse_note(d, fdata, fmime)
    except bm.ApiError:
        raise FErr(400, "bad_voice", "Не удалось отправить запись")
    attach = None
    if voice or note:
        text = ""
    elif fdata:
        if fname.rsplit(".", 1)[-1].lower() in bm.BAD_EXT and "." in fname:
            raise FErr(400, "bad_file", "Такие файлы отправлять нельзя")
        if fname.lower().startswith(("voice.", "circle.")):
            fname = "file_" + fname
        akind, amime = attach_info(fname, fmime)
        attach = (amime, fname)
    sticker = None
    sid = to_int(d.get("sticker_id"))
    if sid:                                  # стикер из набора: обычное сообщение с подписью «🙂 Стикер» + запись в forum_msg_stickers
        import forum_groups
        if text or voice or note or attach or to_int(d.get("post_id")):
            raise FErr(400, "bad_message")
        sticker = await forum_groups._sticker_for_send(sid)
        text = ((sticker["emoji"] + " ") if sticker["emoji"] else "") + "Стикер"
    if not peer or peer == me or (not text and not voice and not note and not attach):
        raise FErr(400, "bad_message")
    if len(EM_RE.findall(text)) > 40:
        raise FErr(400, "too_many_emoji", "Не больше 40 эмодзи из паков в одном сообщении")
    if not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1", peer):
        raise FErr(404, "not_found", "Пользователь не найден")
    by_me, by_peer = await bm.block_state(me, peer)
    if by_me or by_peer:
        raise FErr(403, "blocked", "Сообщения недоступны (блокировка)")
    if not bm.rate_ok(("fdm", me), 0.6):
        raise FErr(429, "too_fast", "Не так быстро")
    ref_post = None   # ответ на пост ленты: только текст, адресат — автор поста
    pid = to_int(d.get("post_id"))
    if pid:
        if not text or voice or note or attach:
            raise FErr(400, "bad_message", "Напишите текст ответа")
        pr = await P().fetchrow("SELECT user_id,title,body FROM forum_posts WHERE id=$1 AND NOT deleted", pid)
        if not pr:
            raise FErr(404, "not_found", "Пост не найден или удалён")
        if pr["user_id"] != peer:
            raise FErr(400, "bad_message")
        ref_post = (pid, (pr["title"] or "").strip() or " ".join((pr["body"] or "").split()))
    reply_to = None
    rt = to_int(d.get("reply_to"))
    if rt and await P().fetchval(
            "SELECT 1 FROM direct_messages WHERE id=$1 AND ((sender_id=$2 AND recipient_id=$3) OR (sender_id=$3 AND recipient_id=$2))", rt, me, peer):
        reply_to = rt
    from support import SUPPORT_ID, on_user_message
    if (voice or note or attach or sticker) and peer == SUPPORT_ID:
        raise FErr(400, "voice_to_support", "Поддержка принимает только текст")
    if voice or note:
        vmime, vname, vdur = (voice or note)[:3] if voice else note
        vwave = voice[3] if voice else None
        mid = await P().fetchval(
            """INSERT INTO direct_messages(sender_id,recipient_id,body,file_data,file_mime,file_name,file_size,voice_dur,voice_wave,reply_to)
               VALUES($1,$2,'',$3,$4,$5,$6,$7,$8,$9) RETURNING id""", me, peer, fdata, vmime, vname, len(fdata), vdur, vwave, reply_to)
        asyncio.create_task(bm.push_dm(me, peer, None, "", vname, vmime))
        return J({"ok": True, "id": mid})
    if attach:
        mid = await P().fetchval(
            """INSERT INTO direct_messages(sender_id,recipient_id,body,file_data,file_mime,file_name,file_size,reply_to)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""", me, peer, text, fdata, attach[0], attach[1], len(fdata), reply_to)
        asyncio.create_task(bm.push_dm(me, peer, None, text, attach[1], attach[0]))
        return J({"ok": True, "id": mid})
    mid = await P().fetchval("INSERT INTO direct_messages(sender_id,recipient_id,body,reply_to) VALUES($1,$2,$3,$4) RETURNING id", me, peer, text, reply_to)
    if sticker:
        await P().execute("INSERT INTO forum_msg_stickers(msg_id,sticker_id) VALUES($1,$2)", mid, sticker["id"])
    if ref_post:
        await P().execute("INSERT INTO forum_msg_posts(msg_id,post_id) VALUES($1,$2) ON CONFLICT DO NOTHING", mid, ref_post[0])
        asyncio.create_task(bm.push_dm(me, peer, None, "↩ Пост «%s»: %s" % (ref_post[1][:40], text), None, None))
        return J({"ok": True, "id": mid})
    if peer == SUPPORT_ID:
        asyncio.create_task(on_user_message(me, text, mid))
    else:
        asyncio.create_task(bm.push_dm(me, peer, None, strip_em(text), None, None))
    return J({"ok": True, "id": mid})


# ============================================================================ предпросмотр ссылок в чате
# Сервер сам скачивает страницу (адрес пользователя сайту не виден), достаёт Open Graph и отдаёт карточку.
# Защита от SSRF: только http/https на 80/443/8080/8443, адрес проверяется при КАЖДОМ подключении (в т.ч. редиректы),
# внутренние/локальные/служебные IP запрещены. Лимиты: 6 с, 512 КБ HTML, 800 КБ картинка, 4 загрузки одновременно.
LP_UA = "Mozilla/5.0 (compatible; KMBPForumLinkPreview/1.0; +preview)"
LP_PORTS = (None, 80, 443, 8080, 8443)
LP_HTML_MAX, LP_IMG_MAX = 512 * 1024, 800 * 1024
LP_TTL, LP_TTL_BAD = 6 * 3600, 600
LP_IMG_MIMES = ("image/jpeg", "image/png", "image/webp", "image/gif")
_lp_cache: dict = {}      # url -> (ts, dict | None)
_lp_imgs: dict = {}       # token -> (bytes, mime)
_lp_busy: dict = {}       # url -> Future (одинаковые запросы не дублируем)
_lp_rate: dict = {}       # uid -> [ts...]
_lp_sem = None


def lp_ip_ok(ip) -> bool:
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


class _SafeResolver(aiohttp.abc.AbstractResolver):
    """Резолвит имя и выбрасывает нерезрешённые адреса — проверка ровно там, где идёт подключение (защита от DNS rebinding)."""

    def __init__(self):
        self._r = aiohttp.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        res = await self._r.resolve(host, port, family)
        ok = [a for a in res if lp_ip_ok(a["host"])]
        if not ok:
            raise OSError("blocked address")
        return ok

    async def close(self):
        await self._r.close()


def lp_url_ok(url: str):
    """Нормализует ссылку и отсекает всё, кроме обычных внешних http(s). Возвращает url или None."""
    url = (url or "").strip()
    if not url or len(url) > 2000 or any(c in url for c in " \r\n\t\x00"):
        return None
    try:
        u = urlsplit(url)
        host, port = u.hostname, u.port
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not host or u.username or u.password or port not in LP_PORTS:
        return None
    if host.lower().rstrip(".") in ("localhost", "localhost.localdomain") or host.lower().endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ipaddress.ip_address(host)           # IP-литерал aiohttp не резолвит — проверяем сами
        if not lp_ip_ok(host):
            return None
    except ValueError:
        pass
    return url


class _OG(HTMLParser):
    """Достаёт title / description / image / site_name. Останавливается на </head>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.m, self.title, self._in_title, self.done = {}, "", False, False

    def handle_starttag(self, tag, attrs):
        if tag == "title" and not self.title:
            self._in_title = True
        elif tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.m:
                self.m[key] = a["content"]

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "head":
            self.done = True

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data


def lp_parse(html_text: str, base: str) -> dict:
    p = _OG()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        pass
    m = p.m
    clean = lambda t, n: " ".join(_html.unescape(str(t or "")).split())[:n]
    img = m.get("og:image") or m.get("og:image:url") or m.get("twitter:image") or m.get("twitter:image:src") or ""
    img = urljoin(base, img.strip()) if img.strip() else ""
    return {"title": clean(m.get("og:title") or m.get("twitter:title") or p.title, 140),
            "desc": clean(m.get("og:description") or m.get("twitter:description") or m.get("description"), 220),
            "site": clean(m.get("og:site_name"), 60), "image_src": img}


async def _lp_read(resp, limit):
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(16384):
        buf += chunk
        if len(buf) >= limit:
            break
    return bytes(buf[:limit])


async def lp_fetch(url: str):
    """Скачивает страницу и (по возможности) картинку. Возвращает dict-карточку или None."""
    global _lp_sem
    if _lp_sem is None:
        _lp_sem = asyncio.Semaphore(4)
    async with _lp_sem:
        conn = aiohttp.TCPConnector(resolver=_SafeResolver(), force_close=True, limit=2)
        tmo = aiohttp.ClientTimeout(total=6, connect=3)
        async with aiohttp.ClientSession(connector=conn, timeout=tmo, trust_env=False, headers={"User-Agent": LP_UA, "Accept-Language": "ru,en;q=0.8"}) as ses:
            async with ses.get(url, max_redirects=3, headers={"Accept": "text/html,application/xhtml+xml"}) as r:
                final = str(r.url)
                if r.status != 200 or not lp_url_ok(final):
                    return None
                ct = (r.headers.get("Content-Type") or "").lower()
                if "html" not in ct:
                    return None
                raw = await _lp_read(r, LP_HTML_MAX)
                enc = r.charset or "utf-8"
            try:
                text = raw.decode(enc or "utf-8", "replace")
            except LookupError:
                text = raw.decode("utf-8", "replace")
            info = lp_parse(text, final)
            host = (urlsplit(final).hostname or "").removeprefix("www.")
            if not info["title"] and not info["desc"]:
                return None
            img_url = None
            src = lp_url_ok(info.pop("image_src"))
            if src:
                try:
                    async with ses.get(src, max_redirects=3, headers={"Accept": "image/*", "Referer": final}) as ir:
                        mime = (ir.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                        clen = int(ir.headers.get("Content-Length") or 0)
                        if ir.status == 200 and mime in LP_IMG_MIMES and clen <= LP_IMG_MAX:
                            data = await _lp_read(ir, LP_IMG_MAX + 1)
                            if 200 < len(data) <= LP_IMG_MAX:
                                tok = secrets.token_urlsafe(12)
                                _lp_imgs[tok] = (data, mime)
                                while len(_lp_imgs) > 80:
                                    _lp_imgs.pop(next(iter(_lp_imgs)))
                                img_url = "/forum/api/lpimg/" + tok
                except Exception:
                    pass
            info.update({"ok": True, "host": host, "img": img_url})
            return info


@api
async def a_linkpreview(request):
    me = request["fuid"]
    now = time.monotonic()
    hist = [t for t in _lp_rate.get(me, []) if now - t < 60]
    if len(hist) >= 60:
        raise FErr(429, "too_fast", "Не так быстро")
    hist.append(now)
    _lp_rate[me] = hist
    if len(_lp_rate) > 3000:
        _lp_rate.clear()
    url = lp_url_ok(request.query.get("url"))
    if not url:
        return J({"ok": False})
    hit = _lp_cache.get(url)
    if hit and now - hit[0] < (LP_TTL if hit[1] else LP_TTL_BAD):
        if hit[1] and hit[1].get("img") and hit[1]["img"].rsplit("/", 1)[-1] not in _lp_imgs:
            hit[1]["img"] = None          # картинка вытеснена из кэша — карточка без неё
        return J(hit[1] or {"ok": False})
    fut = _lp_busy.get(url)
    if fut is None:
        fut = _lp_busy[url] = asyncio.ensure_future(lp_fetch(url))
    try:
        res = await asyncio.shield(fut)
    except Exception:
        res = None
    finally:
        if fut.done():
            _lp_busy.pop(url, None)
    _lp_cache[url] = (time.monotonic(), res)
    while len(_lp_cache) > 500:
        _lp_cache.pop(next(iter(_lp_cache)))
    return J(res or {"ok": False})


async def a_lpimg(request):
    hit = _lp_imgs.get(request.match_info.get("tok", ""))
    if not hit:
        raise web.HTTPNotFound()
    return web.Response(body=hit[0], content_type=hit[1], headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})


MSG_REACTIONS = ("👍", "❤️", "🔥", "😂", "😮", "😢", "🙏", "👎")


@api
async def a_message_react(request):
    """Реакция на сообщение личного чата. Одна реакция на человека: та же — снимает, другая — заменяет. emoji пустой — снять."""
    me = request["fuid"]
    d = await jbody(request)
    mid = to_int(d.get("id"))
    emoji = str(d.get("emoji") or "").strip()
    if emoji and emoji not in MSG_REACTIONS:
        raise FErr(400, "bad_emoji", "Такой реакции нет")
    if not mid or not await P().fetchval("SELECT 1 FROM direct_messages WHERE id=$1 AND (sender_id=$2 OR recipient_id=$2)", mid, me):
        raise FErr(404, "not_found", "Сообщение не найдено")
    if not bm.rate_ok(("frx", me), 0.25):
        raise FErr(429, "too_fast", "Не так быстро")
    cur = await P().fetchval("SELECT emoji FROM forum_msg_reactions WHERE msg_id=$1 AND user_id=$2", mid, me)
    if not emoji or emoji == cur:
        await P().execute("DELETE FROM forum_msg_reactions WHERE msg_id=$1 AND user_id=$2", mid, me)
        mine = None
    else:
        await P().execute(
            "INSERT INTO forum_msg_reactions(msg_id,user_id,emoji) VALUES($1,$2,$3) ON CONFLICT(msg_id,user_id) DO UPDATE SET emoji=EXCLUDED.emoji, created_at=now()",
            mid, me, emoji)
        mine = emoji
    return J({"ok": True, "mine": mine})


@api
async def a_voice_heard(request):
    """Получатель начал слушать голосовое — снимаем «непрослушано»."""
    mid = to_int((await jbody(request)).get("id"))
    if mid:
        await P().execute("UPDATE direct_messages SET voice_heard=now() WHERE id=$1 AND recipient_id=$2 AND voice_dur IS NOT NULL AND voice_heard IS NULL",
                          mid, request["fuid"])
    return J({"ok": True})


@api
async def a_support_act(request):
    """Кнопки поддержки в чате форума: вызвать оператора / отменить вызов (та же логика, что в мини-аппе)."""
    me = request["fuid"]
    import support
    act = request.match_info.get("act")
    if act == "operator":
        if not await support.open_ticket(me):
            await support.ensure_chat(me)
            if not bm.rate_ok(("support_op", me), 20):
                raise FErr(429, "too_fast", "Не так быстро")
            await support.create_ticket(me, announce=True)
    elif act == "cancel":
        await support.user_cancel(me)          # ожидание → отмена; разговор с оператором → завершён, дальше ИИ
    else:
        raise FErr(404, "not_found")
    return J({"ok": True, "mode": await support.mode_of(me)})


@api
async def a_typing(request):
    d = await jbody(request)
    peer = to_int(d.get("peer"))
    if peer:
        bm._typing[(request["fuid"], peer, {"rec": 1, "vid": 2}.get(d.get("kind"), 0))] = time.monotonic()
    return J({"ok": True})


# ============================================================================ сама страница
def _page():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forum.html")
    with open(p, encoding="utf-8") as f:
        return f.read()


async def page(request):
    global _auto_base
    if not os.getenv("FORUM_URL"):
        proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "https").split(",")[0].strip()
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
        if host:
            _auto_base = f"{proto}://{host}"
    html = _page().replace("__BASE__", (os.getenv("FORUM_URL") or _auto_base or bm.WEBAPP_URL or "").rstrip("/"))
    hdr = {"Cache-Control": "no-cache"}
    if request.query.get("dl"):
        hdr["Content-Disposition"] = 'attachment; filename="kmbp-forum.html"'
    return web.Response(text=html, content_type="text/html", charset="utf-8", headers=hdr)


# ============================================================================ профиль как в мини-аппе
# Те же обработчики, что у мини-аппа (bot.py): рейтинг, отзывы, сделки, достижения, проекты, жалобы, блокировки,
# выдача значков. Подменяем только способ авторизации: вместо Telegram initData — токен форума.
ERR_RU = {
    "review_after_deal_only": "Оставить отзыв можно после завершённой сделки",
    "bad_image": "Нужна картинка до 5 МБ (JPEG, PNG, WebP)", "too_many_photos": "Не больше 5 скриншотов",
    "slow": "Слишком часто — подождите немного", "forbidden": "Недостаточно прав", "user_not_found": "Пользователь не найден",
    "review_not_found": "Отзыв не найден", "bad_review": "Нельзя оценить себя или оценка неверная", "bad_input": "Неверные данные",
    "message_not_found": "Сообщение не найдено", "too_long": "Слишком длинное сообщение", "empty": "Сообщение не может быть пустым",
    "blocked_by_peer": "Пользователь ограничил вам сообщения", "bad_id": "Неверное сообщение",
    "bad_theme": "Неизвестная тема", "bad_accent": "Неверный цвет", "blocked_peer": "Вы заблокировали этого пользователя",
}


def bridge(name):
    """Эндпоинт форума, вызывающий обработчик мини-аппа bm.<name> от имени пользователя форума."""
    @api
    async def handler(request):
        request["u"] = {"id": request["fuid"]}
        try:
            return await getattr(bm, name)(request)
        except bm.ApiError as e:
            raise FErr(e.status, e.msg, ERR_RU.get(e.msg, e.msg))
    return handler


@api
async def a_x_avatar_delete(request):
    await P().execute("UPDATE users SET avatar_data=NULL,avatar_mime=NULL,tg_avatar_at=NULL WHERE user_id=$1", request["fuid"])
    return J({"ok": True})


@api
async def a_x_banner_delete(request):
    await P().execute("UPDATE users SET banner_data=NULL,banner_mime=NULL WHERE user_id=$1", request["fuid"])
    return J({"ok": True})



def install(app, bot_module):
    global bm
    bm = bot_module
    app.middlewares.append(cors_mw)
    r = app.router
    r.add_get("/forum", page)
    r.add_get("/forum/", page)
    r.add_get("/forum/app.html", page)
    r.add_get("/exg/{name}", exg_redirect)
    r.add_get("/forum/exg/{name}", exg_redirect)
    A = "/forum/api"
    r.add_get(A + "/boot", a_boot)
    r.add_post(A + "/auth/start", a_auth_start)
    r.add_get(A + "/auth/poll", a_auth_poll)
    r.add_post(A + "/auth/logout", a_logout)
    r.add_get(A + "/me", a_me)
    r.add_post(A + "/me/update", a_me_update)
    r.add_post(A + "/me/avatar", a_me_avatar)
    r.add_post(A + "/me/banner", a_me_banner)
    r.add_get(A + "/avatar/{uid}", a_avatar)
    r.add_get(A + "/banner/{uid}", a_banner)
    r.add_get(A + "/img/{iid}", a_img)
    r.add_get(A + "/linkpreview", a_linkpreview)
    r.add_get(A + "/lpimg/{tok}", a_lpimg)
    r.add_get(A + "/resolve", a_resolve)
    r.add_get(A + "/name/check", a_name_check)
    r.add_get(A + "/user", a_user)
    r.add_get(A + "/user/list", a_user_list)
    r.add_post(A + "/follow", a_follow)
    r.add_get(A + "/feed", a_feed)
    r.add_get(A + "/post", a_post_get)
    r.add_post(A + "/post", a_post_create)
    r.add_post(A + "/post/edit", a_post_edit)
    r.add_post(A + "/post/delete", a_post_delete)
    r.add_post(A + "/post/pin", a_post_pin)
    r.add_post(A + "/like", a_like)
    r.add_post(A + "/bookmark", a_bookmark)
    r.add_post(A + "/comment", a_comment)
    r.add_post(A + "/comment/edit", a_comment_edit)
    r.add_post(A + "/comment/delete", a_comment_delete)
    r.add_post(A + "/report", a_report)
    r.add_post(A + "/board", a_board_save)
    r.add_post(A + "/board/delete", a_board_delete)
    r.add_get(A + "/notifs", a_notifs)
    r.add_post(A + "/notifs/read", a_notifs_read)
    r.add_get(A + "/notifs/prefs", a_notif_prefs)
    r.add_post(A + "/notifs/prefs", a_notif_prefs_set)
    r.add_get(A + "/ping", a_ping)
    r.add_get(A + "/search", a_search)
    r.add_get(A + "/chats", a_chats)
    r.add_get(A + "/chats/search", a_chats_search)
    r.add_post(A + "/chats/pref", a_chat_pref)
    r.add_get(A + "/messages", a_messages)
    r.add_post(A + "/messages", a_message_send)
    r.add_post(A + "/messages/heard", a_voice_heard)
    r.add_post(A + "/messages/react", a_message_react)
    # действия с сообщениями — те же обработчики, что и в мини-аппе (изменить, удалить, закрепить, переслать)
    r.add_post(A + "/messages/edit", bridge("api_message_edit"))
    r.add_post(A + "/messages/delete", bridge("api_message_delete"))
    r.add_post(A + "/messages/pin", bridge("api_message_pin"))
    r.add_post(A + "/messages/forward", bridge("api_message_forward"))
    r.add_post(A + "/typing", a_typing)
    import forum_groups
    forum_groups.install(r, A)
    import forum_gifs
    forum_gifs.install(r, A)
    import forum_calls
    forum_calls.install(r, A)                  # звонки: личные и групповые (WebRTC, сигнализация через long-poll)
    r.add_post(A + "/support/{act}", a_support_act)
    X = A + "/x"
    r.add_get(X + "/profile", bridge("api_profile"))
    r.add_post(X + "/profile", bridge("api_profile_update"))
    r.add_get(X + "/reviews", bridge("api_profile_reviews"))
    r.add_post(X + "/review", bridge("api_profile_review_save"))
    r.add_get(X + "/blocks", bridge("api_blocks"))
    r.add_post(X + "/block", bridge("api_block"))
    r.add_post(X + "/report_user", bridge("api_report_user"))
    r.add_post(X + "/report_any", bridge("api_report_any"))
    r.add_post(X + "/user_flag", bridge("api_admin_user_flag"))
    r.add_post(X + "/user_badge", bridge("api_admin_user_badge"))
    r.add_post(X + "/avatar/delete", a_x_avatar_delete)
    r.add_post(X + "/banner/delete", a_x_banner_delete)


async def start(bot_module):
    """Вызывается в main() после init_db() и support.start()."""
    global bm
    bm = bot_module
    await bm.pool.execute(DDL)
    import forum_groups, forum_names
    await bm.pool.execute(forum_names.DDL)         # внутренние юзернеймы и ссылки exg/имя
    await bm.pool.execute(forum_groups.DDL)        # группы, каналы, стикеры (после forum_boards / forum_notifs / direct_messages)
    await forum_groups.backfill_names()            # старым наборам стикеров — ссылки
    import forum_gifs
    await bm.pool.execute(forum_gifs.DDL)          # «Мои GIF»
    if not await bm.pool.fetchval("SELECT 1 FROM forum_boards LIMIT 1"):
        for name, emoji, sort, admin_only in SEED_BOARDS:
            await bm.pool.execute("INSERT INTO forum_boards(name,emoji,sort,admin_only) VALUES($1,$2,$3,$4)", name, emoji, sort, admin_only)
    import forum_calls
    forum_calls.start()                            # фоновая уборка звонков (таймаут вызова, отвалившиеся участники)
    log.info("forum ready")
