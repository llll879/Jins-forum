# -*- coding: utf-8 -*-
"""
botcore.py — общее ядро бота для форума. СГЕНЕРИРОВАНО из bot.py (tools/split.py), вручную не править.

Форум (forum.py, forum_groups.py, support.py) раньше работал внутри процесса бота и обращался к его модулю
как к «bm» (пул БД, профили, ЛС, пуши, значки, блокировки…). Теперь форум — отдельный сервис, а эти же
самые функции лежат здесь, поэтому логика профилей/ЛС/значков/отзывов одинакова в боте и в форуме.
Состояние (pool, _BOT, BOT_USERNAME, HTTP) выставляет main.py форума.
"""
import asyncio
import base64
import hashlib
import hmac
import html
import io
import json
import logging
import os
import random
import re
import time
import secrets
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote
from zoneinfo import ZoneInfo

import asyncpg
from aiohttp import ClientError, ClientSession, ClientTimeout, web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InputMediaPhoto, KeyboardButton, MenuButtonWebApp, Message,
    ReplyKeyboardMarkup, ReplyParameters, WebAppInfo, LabeledPrice, PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


log = logging.getLogger("kmbp_exchange")


BOT_TOKEN = os.environ["BOT_TOKEN"]


DATABASE_URL = os.environ["DATABASE_URL"]


OWNER_ID = int(os.environ["OWNER_ID"])  # старший админ (ваш Telegram ID)


TZ = ZoneInfo(os.getenv("TZ_NAME", "Europe/Moscow"))


GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")


GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash").split(",") if m.strip()]


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


RETRY_CODES = {408, 429, 500, 502, 503, 504}


WEBAPP_URL = (os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


MINIAPP_LINK = (os.getenv("MINIAPP_LINK") or "").rstrip("/")      # например https://t.me/mybot/app


MINIAPP_SHORT = (os.getenv("MINIAPP_SHORT") or "").strip().strip("/")  # short name мини-аппа из BotFather


BOT_USERNAME = ""


_BOT = None


_typing = {}    # (отправитель, получатель, объявление) -> monotonic последнего «печатает»


_viewing = {}   # (кто смотрит, с кем, объявление) -> monotonic последнего открытия чата


pool: asyncpg.Pool


HTTP: ClientSession


EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)


def strip_emoji(v: str) -> str:
    return EMOJI_RE.sub(r"\1", v)


class SafeSession(AiohttpSession):
    """Если Telegram не принял премиум-эмодзи — повторяем отправку с обычными."""

    async def make_request(self, bot, method, timeout=None):
        try:
            return await super().make_request(bot, method, timeout)
        except TelegramBadRequest:
            upd = {}
            for f in ("text", "caption"):
                v = getattr(method, f, None)
                if isinstance(v, str) and "<tg-emoji" in v:
                    upd[f] = strip_emoji(v)
            if not upd:
                raise
            return await super().make_request(bot, method.model_copy(update=upd), timeout)


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def strip_html(t: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", t or ""))


def fmt_dt(dt):
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


_rl = {}


def rate_ok(key, secs):
    now = time.monotonic()
    if now - _rl.get(key, 0) < secs:
        return False
    if len(_rl) > 5000:
        _rl.clear()
    _rl[key] = now
    return True


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def get_setting(key):
    return await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)


async def set_setting(key, value):
    await pool.execute(
        "INSERT INTO settings(key,value) VALUES($1,$2) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", key, str(value))


async def role(uid):
    if uid == OWNER_ID:
        return "owner"
    return await pool.fetchval("SELECT role FROM admins WHERE user_id=$1", uid)


async def is_main(uid):
    return await role(uid) in ("owner", "main")


async def review_deal_info(a, b):
    """Последняя завершённая сделка между двумя людьми: dict(kind,id,buyer_id,seller_id,amount,terms,title) или None."""
    row = await pool.fetchrow("""
        SELECT * FROM (
          SELECT 'direct'::text kind, id, buyer_id, seller_id, amount, terms, listing_post_id, COALESCE(closed_at,updated_at) ts
            FROM direct_deals WHERE status='completed' AND ((buyer_id=$1 AND seller_id=$2) OR (buyer_id=$2 AND seller_id=$1))
          UNION ALL
          SELECT 'escrow'::text, id, buyer_id, seller_id, amount, terms, listing_post_id, COALESCE(closed_at,updated_at)
            FROM escrow_deals WHERE status='completed' AND ((buyer_id=$1 AND seller_id=$2) OR (buyer_id=$2 AND seller_id=$1))
        ) x ORDER BY ts DESC NULLS LAST LIMIT 1""", int(a), int(b))
    if not row:
        return None
    d = dict(row)
    title = ""
    if d.get("listing_post_id"):
        txt = await pool.fetchval("SELECT text FROM posts WHERE id=$1", d["listing_post_id"])
        lines = [x.strip() for x in strip_html(txt or "").splitlines() if x.strip()]
        title = lines[0] if lines else ""
    if not title:
        title = (d.get("terms") or "").strip().replace("\n", " ")
    d["title"] = title[:200] or "без названия"
    return d


async def remove_review_post(bot, rid):
    """Удаляет из группы пост(ы) отзыва. Не критично при сбое."""
    row = await pool.fetchrow("SELECT pub_chat_id,pub_msg_ids FROM user_reviews WHERE id=$1", int(rid))
    bot = bot or _BOT
    if not row or bot is None or not row["pub_chat_id"] or not row["pub_msg_ids"]:
        return
    for mid in row["pub_msg_ids"]:
        try:
            await bot.delete_message(int(row["pub_chat_id"]), int(mid))
        except Exception:
            log.warning("cannot delete review message %s", mid, exc_info=True)
    await pool.execute("UPDATE user_reviews SET pub_msg_ids='{}' WHERE id=$1", int(rid))


async def publish_review(bot, rid, edited=False):
    """Публикует отзыв в выбранную тему группы (/setreviews). Если отзыв изменён — старый пост заменяется новым."""
    chat = await get_setting("rev_chat")
    if not chat:
        return False
    bot = bot or _BOT
    if bot is None:
        return False
    thread = int(await get_setting("rev_thread") or 0) or None
    r = await pool.fetchrow("""SELECT id,reviewer_id,target_id,rating,text,created_at,updated_at,deal_kind,deal_id,
        (photo_data IS NOT NULL) has_photo, photo_data, pub_chat_id, pub_msg_ids FROM user_reviews WHERE id=$1""", int(rid))
    if not r:
        return False
    if r["pub_msg_ids"]:
        await remove_review_post(bot, rid)
    deal = await review_deal_info(r["reviewer_id"], r["target_id"])
    if deal:
        buyer, seller = deal["buyer_id"], deal["seller_id"]
    else:
        buyer, seller = r["reviewer_id"], r["target_id"]
    role_txt = "покупатель" if r["reviewer_id"] == buyer else "продавец"
    rt = (await seller_ratings([r["target_id"]])).get(r["target_id"])
    L = [f"{'✏️ <b>Отзыв изменён</b>' if edited else '⭐ <b>Новый отзыв</b>'} · <code>Exg:/r{r['id']}</code>", "",
         f"<b>{stars_txt(r['rating'])}  {r['rating']}/5</b>",
         f"🛍 <b>Услуга:</b> {esc(deal['title']) if deal else 'не определена'}"]
    if deal:
        kind = "через гаранта" if deal["kind"] == "escrow" else "напрямую"
        L.append(f"🤝 <b>Сделка:</b> #{deal['id']} · {kind} · {int(deal['amount'] or 0)} ⭐")
    L += ["", f"🛒 <b>Покупатель:</b> {await who_html(buyer)}",
          f"🏷 <b>Продавец:</b> {await who_html(seller)}",
          f"✍️ <b>Автор отзыва:</b> {role_txt}", "", "💬 <b>Отзыв:</b>"]
    L.append(f"<blockquote>{esc(r['text'])}</blockquote>" if (r["text"] or "").strip() else "<i>без текста</i>")
    tail = f"🕒 {fmt_dt(r['created_at'])}"
    if edited:
        tail += f" · изменён {fmt_dt(r['updated_at'])}"
    L += ["", tail]
    if rt:
        L.append(f"📊 Рейтинг получателя: <b>{rt[0]}</b> · отзывов: {rt[1]}")
    ids = []
    try:
        m = await bot.send_message(int(chat), "\n".join(L), message_thread_id=thread)
        ids.append(m.message_id)
        if r["has_photo"]:
            ph = await bot.send_photo(int(chat), BufferedInputFile(bytes(r["photo_data"]), "review.jpg"),
                                      caption=f"📷 Скриншот к отзыву #{r['id']}", message_thread_id=thread,
                                      reply_to_message_id=m.message_id)
            ids.append(ph.message_id)
        return True
    except Exception:
        log.exception("publish review to group failed")
        return bool(ids)
    finally:
        if ids:
            try:
                await pool.execute("UPDATE user_reviews SET pub_chat_id=$2, pub_msg_ids=$3 WHERE id=$1",
                                   int(rid), int(chat), ids)
            except Exception:
                log.exception("cannot save review message ids")


async def deliver_card(bot: Bot, text, markup, photo=None):
    """Отправляет карточку (заявку/анкету) на проверку.
    Сначала — в группу модерации; если она не задана или недоступна (бот не в группе, чат
    переехал и т.п.) — в личку владельцу и главным админам, чтобы заявка не терялась.
    photo — file_id (str) или BufferedInputFile; картинка уходит отдельным сообщением,
    карточка — ответом на неё. Возвращает (первое_сообщение | None, file_id | None)."""
    st = {"photo": photo, "fid": photo if isinstance(photo, str) else None}

    async def send(cid):
        reply = None
        if st["photo"] is not None:
            pm = await bot.send_photo(cid, st["photo"])
            if st["fid"] is None:
                st["fid"] = pm.photo[-1].file_id
                st["photo"] = st["fid"]
            reply = ReplyParameters(message_id=pm.message_id, allow_sending_without_reply=True)
        return await bot.send_message(cid, text, reply_markup=markup, reply_parameters=reply)

    first = None
    mod = await get_setting("mod_chat")
    if mod:
        try:
            first = await send(int(mod))
        except Exception as e:
            log.warning("mod chat %s unavailable (%s) — шлём в личку админам", mod, e)
    if first is None:
        staff = [OWNER_ID] + [r["user_id"] for r in await pool.fetch(
            "SELECT user_id FROM admins WHERE role='main' ORDER BY user_id") if r["user_id"] != OWNER_ID]
        for cid in staff:
            try:
                msg = await send(cid)
                first = first or msg
            except Exception as e:
                log.warning("cannot DM staff %s: %s", cid, e)
    return first, st["fid"]


async def register_user(user):
    await pool.execute(
        "INSERT INTO users(user_id,username,first_name,last_name,last_seen) VALUES($1,$2,$3,$4,now()) "
        "ON CONFLICT(user_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name, "
        "last_name=EXCLUDED.last_name, last_seen=now()",
        user.id, user.username, user.first_name, user.last_name)
    await track_username(user.id, user.username)


BASE_ROLES = {"admin": ("Админ", "админ"), "seller": ("Продавец", "продавец"),
              "pr": ("Пиарщик", "пиарщик"), "editor": ("Монтажёр", "монтажёр")}


BASE_WORD = {5: "Отличный", 4: "Хороший", 3: "Так себе", 2: "Плохой", 1: "Ужасный"}


BASE_TIERS = {5: "top", 4: "good", 3: "mid", 2: "low", 1: "awful", 0: "none"}


BASE_HINT = {
    "top": "Отличная репутация — с таким человеком можно работать спокойно.",
    "good": "Хорошая репутация, нареканий нет.",
    "mid": "Репутация средняя — будьте внимательны и уточняйте детали.",
    "low": "Плохая репутация — лучше работать только через гаранта.",
    "awful": "Ужасная репутация — мы не рекомендуем иметь с ним дело.",
    "none": "Особых отметок нет — обычный участник.",
    "minus": "На человека много жалоб — он под подозрением. Только через гаранта!",
    "scam": "Помечен модераторами как мошенник. Не проводите сделки!",
}


BASE_MINUS_REPORTS = max(1, int(os.getenv("BASE_MINUS_REPORTS", "3") or 3))


BASE_REPORT_CATS = ["Скам / обман", "Не выполнил условия", "Выдаёт себя за другого",
                    "Спам / реклама", "Оскорбления", "Другое"]


def eff_score(manual, avg, cnt):
    """Единый рейтинг человека — одно и то же число на бирже и в VETRIXBASE.
    Админ поставил звёзды вручную (1–5) — берём их; иначе среднее по отзывам (до десятых); иначе 0."""
    manual = int(manual or 0)
    if 1 <= manual <= 5:
        return manual
    if cnt and avg:
        v = round(float(avg), 1)
        return int(v) if v == int(v) else v
    return 0


def score_stars(score, avg=None, manual=0):
    """Целые звёзды 0–5 для плашек/уровней: ручные как есть, иначе среднее по отзывам, округлённое как в SQL (.5 вверх)."""
    manual = int(manual or 0)
    if 1 <= manual <= 5:
        return manual
    base = float(avg) if avg else float(score or 0)
    return max(0, min(5, int(base + 0.5)))


BASE_SQL = """
SELECT u.user_id, u.username, u.first_name, u.last_name, u.created_at, u.bio, u.verified, u.scam,
  u.badge_dev, u.badge_adm, u.badge_badrep, u.badge_scam, u.base_stars, u.base_role, u.base_note, u.base_set_at,
  (u.avatar_data IS NOT NULL) has_avatar, u.photo_url,
  (SELECT count(*) FROM escrow_deals d WHERE d.status='completed' AND (d.buyer_id=u.user_id OR d.seller_id=u.user_id))
  + (SELECT count(*) FROM direct_deals d WHERE d.status='completed' AND (d.buyer_id=u.user_id OR d.seller_id=u.user_id)) deals,
  (SELECT avg(rating) FROM user_reviews r WHERE r.target_id=u.user_id)::float rating,
  (SELECT count(*) FROM user_reviews r WHERE r.target_id=u.user_id) reviews,
  (SELECT count(*) FROM escrow_deals d WHERE d.seller_id=u.user_id AND d.status IN ('refunded','refund_pending')) refunds,
  (SELECT count(DISTINCT reporter_id) FROM user_reports x WHERE x.target_id=u.user_id AND x.status='new') reports,
  (SELECT count(DISTINCT reporter_id) FROM user_reports x WHERE x.target_id=u.user_id) reports_all,
  (SELECT array_agg(h.username ORDER BY h.seen_at DESC) FROM username_history h
     WHERE h.user_id=u.user_id AND lower(h.username) <> lower(COALESCE(u.username,''))) aliases
FROM users u WHERE u.user_id = ANY($1::bigint[])"""


_uname_seen = {}


async def track_username(uid, username):
    """Запоминает юзернейм в истории (только когда он изменился с прошлого раза)."""
    username = (username or "").strip().lstrip("@")
    if not username or _uname_seen.get(uid) == username.lower():
        return
    if len(_uname_seen) > 20000:
        _uname_seen.clear()
    _uname_seen[uid] = username.lower()
    try:
        await pool.execute(
            "INSERT INTO username_history(user_id,username) VALUES($1,$2) "
            "ON CONFLICT(user_id, lower(username)) DO UPDATE SET seen_at=now(), username=EXCLUDED.username",
            uid, username)
    except Exception:
        log.exception("track_username failed")


def base_label(stars, role_key):
    if stars <= 0:
        return "Обычный пользователь"
    noun = BASE_ROLES[role_key][1] if role_key in BASE_ROLES else "участник"
    return f"{BASE_WORD[stars]} {noun}"


def base_card(r, via=None):
    manual = max(0, min(5, int(r["base_stars"] or 0)))
    score = eff_score(manual, r["rating"], r["reviews"])
    stars = score_stars(score, r["rating"], manual)
    rk = r["base_role"] if r["base_role"] in BASE_ROLES else ""
    reports = int(r["reports"] or 0)
    minus = "scam" if r["scam"] else ("reports" if reports >= BASE_MINUS_REPORTS else None)
    tier = "scam" if minus == "scam" else ("minus" if minus else BASE_TIERS[stars])
    un, uid = r["username"], r["user_id"]
    name = " ".join(x for x in [r["first_name"], r["last_name"]] if x) or un or "Пользователь"
    return {
        "id": uid, "username": un, "name": name, "bio": r["bio"] or "",
        "has_avatar": bool(r["has_avatar"]), "photo_url": r["photo_url"],
        "code": "Exg:/" + (f"@{un}" if un else f"u{uid}"),
        "created": r["created_at"].astimezone(TZ).strftime("%d.%m.%Y"),
        "stars": stars, "score": score, "manual": manual, "role": rk, "role_title": BASE_ROLES[rk][0] if rk else "",
        "label": base_label(stars, rk), "tier": tier, "minus": minus,
        "status": "Мошенник" if minus == "scam" else ("Ненадёжный" if minus else base_label(stars, rk)),
        "hint": BASE_HINT[tier],
        "rating": round(r["rating"], 1) if r["rating"] else 0, "reviews": int(r["reviews"] or 0),
        "deals": int(r["deals"] or 0), "reports": reports, "reports_all": int(r["reports_all"] or 0),
        "aliases": list(r["aliases"] or []), "note": r["base_note"] or "",
        "rated_at": r["base_set_at"].astimezone(TZ).strftime("%d.%m.%Y") if r["base_set_at"] else "",
        "badges": _badges(r),
        "sb": ("d" if r["badge_dev"] else "") + ("a" if r["badge_adm"] else "") + ("b" if r["badge_badrep"] else "") + ("s" if r["badge_scam"] else ""),
        "via": via,
    }


async def base_cards(ids):
    ids = list({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = await pool.fetch(BASE_SQL, ids)
    return {r["user_id"]: base_card(r) for r in rows}


def stars_txt(n):
    return "★" * n + "☆" * (5 - n)


class ApiError(Exception):
    def __init__(self, status, msg):
        self.status, self.msg = status, msg


def jr(data, status=200):
    resp = _jr(data, status)
    try:
        resp.enable_compression()
    except Exception:
        pass
    return resp


def _jr(data, status=200):
    return web.json_response(
        data, status=status,
        dumps=lambda o: json.dumps(
            o, ensure_ascii=False, default=lambda x: x.isoformat() if hasattr(x, "isoformat") else (float(x) if x.__class__.__name__ == "Decimal" else str(x))))


async def body(request):
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


async def need_main(request):
    if not await is_main(request["u"]["id"]):
        raise ApiError(403, "forbidden")


_IMG_KEY = hashlib.sha256(b"kmbp-img:" + BOT_TOKEN.encode()).digest()


def img_url(kind, ident):
    sig = hmac.new(_IMG_KEY, f"{kind}:{ident}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"/img/{kind}/{ident}?t={sig}"


async def seller_ratings(user_ids):
    """{user_id: (единый рейтинг, число отзывов)} — то же число, что и в «VETRIXBASE»."""
    ids = list({int(i) for i in user_ids if i})
    if not ids:
        return {}
    rows = await pool.fetch("""SELECT u.user_id, u.base_stars, avg(r.rating)::float a, count(r.id)::int c
        FROM users u LEFT JOIN user_reviews r ON r.target_id=u.user_id
        WHERE u.user_id = ANY($1::bigint[]) GROUP BY u.user_id""", ids)
    return {r["user_id"]: (eff_score(r["base_stars"], r["a"], r["c"]), r["c"]) for r in rows}


async def avatar_info(ids):
    """{user_id: (has_custom_avatar, telegram_photo_url)} для списка пользователей."""
    ids = list({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = await pool.fetch("SELECT user_id,(avatar_data IS NOT NULL) has_avatar,photo_url FROM users WHERE user_id=ANY($1::bigint[])", ids)
    return {r["user_id"]: (bool(r["has_avatar"]), r["photo_url"]) for r in rows}


async def staff_badges(ids):
    """{user_id: "d"|"a"|"da"} — значки рядом с ником: d = разработчик (ближе к нику), a = админ, b = BAD REP, s = SCAM. Выдаёт только OWNER_ID."""
    ids = list({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = await pool.fetch("SELECT user_id,badge_dev,badge_adm,badge_badrep,badge_scam FROM users WHERE user_id=ANY($1::bigint[]) AND (badge_dev OR badge_adm OR badge_badrep OR badge_scam)", ids)
    return {r["user_id"]: ("d" if r["badge_dev"] else "") + ("a" if r["badge_adm"] else "") + ("b" if r["badge_badrep"] else "") + ("s" if r["badge_scam"] else "") for r in rows}


IMG_MIMES = ("image/jpeg", "image/png", "image/webp", "image/gif")


BAD_EXT = {"exe", "apk", "bat", "cmd", "scr", "msi", "jar", "com", "vbs", "ps1", "sh", "dmg", "lnk", "pif", "js"}


MAX_FILE = 8 * 1024 * 1024


VOICE_MIMES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3",
               "audio/aac": "aac", "audio/wav": "wav", "audio/x-m4a": "m4a"}


MAX_VOICE_MS = 10 * 60 * 1000


MIN_VOICE_MS = 500


_VOICE_WAVE_RE = re.compile(r"[0-9a-v]{8,128}")


def voice_mime(m):
    """Нормализует mime записи (убирает ;codecs=…); None — не наш формат."""
    m = str(m or "").split(";")[0].strip().lower()
    return m if m in VOICE_MIMES else None


NOTE_MIMES = {"video/mp4": "mp4", "video/webm": "webm"}


MAX_NOTE_MS = 61 * 1000


MIN_NOTE_MS = 800


def note_mime(m):
    m = str(m or "").split(";")[0].strip().lower()
    return m if m in NOTE_MIMES else None


def parse_note(d, fdata, fmime):
    """Если приложен кружок — проверяет и возвращает (mime, имя, мс), иначе None."""
    if not fdata or not d.get("note_dur"):
        return None
    nm = note_mime(fmime)
    try:
        dur = int(float(d.get("note_dur")))
    except (TypeError, ValueError):
        dur = 0
    if not nm or dur < MIN_NOTE_MS or dur > MAX_NOTE_MS:
        raise ApiError(400, "bad_note")
    return nm, "circle." + NOTE_MIMES[nm], dur


def parse_voice(d, fdata, fmime):
    """Если к сообщению приложена голосовая запись — проверяет поля и возвращает (mime, имя, мс, волна), иначе None."""
    if not fdata or not d.get("voice_dur"):
        return None
    vm = voice_mime(fmime)
    try:
        dur = int(float(d.get("voice_dur")))
    except (TypeError, ValueError):
        dur = 0
    wave = str(d.get("voice_wave") or "")
    if not vm or dur < MIN_VOICE_MS or dur > MAX_VOICE_MS or not _VOICE_WAVE_RE.fullmatch(wave):
        raise ApiError(400, "bad_voice")
    return vm, "voice." + VOICE_MIMES[vm], dur, wave


def ranged_audio(request, data, mime, headers):
    """Аудио с поддержкой Range — без него Safari/iOS не играют и не перематывают голосовые."""
    h = dict(headers, **{"Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff"})
    size = len(data)
    m = re.match(r"bytes=(\d*)-(\d*)$", (request.headers.get("Range") or "").strip())
    if m and (m.group(1) or m.group(2)):
        a, b = m.groups()
        start, end = (max(size - int(b), 0), size - 1) if not a else (int(a), min(int(b), size - 1) if b else size - 1)
        if start > end or start >= size:
            return web.Response(status=416, headers={"Content-Range": "bytes */%d" % size})
        h["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
        return web.Response(status=206, body=data[start:end + 1], content_type=mime, headers=h)
    return web.Response(body=data, content_type=mime, headers=h)


def _badges(r):
    deals, rating, reviews = r["deals"] or 0, r["rating"] or 0, r["reviews"] or 0
    bad, good = [], []
    if r["scam"]:
        bad.append({"k": "scam", "t": "Мошенник", "i": "🚫"})
    if reviews >= 3 and rating < 3.0:
        bad.append({"k": "badrev", "t": "Плохие отзывы", "i": "👎"})
    if r["refunds"] >= 2:
        bad.append({"k": "disputes", "t": "Частые возвраты", "i": "⚠️"})
    if r["reports"] >= 3:
        bad.append({"k": "reports", "t": "Много жалоб", "i": "🚩"})
    if not bad:
        if r["verified"] or (deals >= 5 and reviews >= 3 and rating >= 4.5):
            good.append({"k": "verified", "t": "Проверенный", "i": "✅"})
        if deals >= 100:
            good.append({"k": "deals100", "t": "100+ сделок", "i": "🤝"})
        if deals >= 20 and reviews >= 10 and rating >= 4.7:
            good.append({"k": "top", "t": "Топ-продавец", "i": "🏆"})
    return [dict(x, tone="bad") for x in bad] + [dict(x, tone="good") for x in good]


async def user_badges(ids):
    ids = list({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = await pool.fetch("""
        SELECT u.user_id, u.verified, u.scam,
          (SELECT count(*) FROM escrow_deals d WHERE d.status='completed' AND (d.buyer_id=u.user_id OR d.seller_id=u.user_id))
          + (SELECT count(*) FROM direct_deals d WHERE d.status='completed' AND (d.buyer_id=u.user_id OR d.seller_id=u.user_id)) deals,
          (SELECT avg(rating) FROM user_reviews r WHERE r.target_id=u.user_id)::float rating,
          (SELECT count(*) FROM user_reviews r WHERE r.target_id=u.user_id) reviews,
          (SELECT count(*) FROM escrow_deals d WHERE d.seller_id=u.user_id AND d.status IN ('refunded','refund_pending')) refunds,
          (SELECT count(DISTINCT reporter_id) FROM user_reports x WHERE x.target_id=u.user_id AND x.status='new') reports
        FROM users u WHERE u.user_id=ANY($1::bigint[])""", ids)
    out = {i: [] for i in ids}
    for r in rows:
        out[r["user_id"]] = _badges(r)
    return out


async def block_state(uid, peer):
    rows = await pool.fetch(
        "SELECT blocker_id FROM user_blocks WHERE (blocker_id=$1 AND blocked_id=$2) OR (blocker_id=$2 AND blocked_id=$1)",
        uid, peer)
    return any(r["blocker_id"] == uid for r in rows), any(r["blocker_id"] == peer for r in rows)


async def need_not_blocked(uid, peer):
    by_me, by_peer = await block_state(uid, peer)
    if by_me:
        raise ApiError(403, "blocked_peer")
    if by_peer:
        raise ApiError(403, "blocked_by_peer")


async def user_name(uid):
    u = await pool.fetchrow("SELECT username,first_name,last_name FROM users WHERE user_id=$1", uid)
    if not u:
        return str(uid)
    return " ".join(x for x in [u["first_name"], u["last_name"]] if x) or (("@" + u["username"]) if u["username"] else str(uid))


def dm_preview(body, fname, fmime):
    if body:
        return body
    if fname:
        if fname.startswith("voice.") and voice_mime(fmime):
            return "🎤 Голосовое сообщение"
        if fname.startswith("circle.") and note_mime(fmime):
            return "📹 Видеосообщение"
        if fmime == "image/gif":
            return "GIF"
        if fmime in IMG_MIMES:
            return "📷 Фото"
        if fmime in ("video/mp4", "video/webm", "video/quicktime"):
            return "🎬 Видео"
        return "📎 " + fname
    return ""


def app_link(param):
    """Ссылка, открывающая мини-приложение сразу на нужном месте (профиль/объявление/отзыв)."""
    base = share_base()
    return f"{base}?startapp={param}" if base else ""


async def who_html(uid):
    """Кликабельная строка о пользователе для админ-чата: имя → профиль в приложении, @ник, ID, код Exg:/…"""
    r = await pool.fetchrow("SELECT username,first_name,last_name FROM users WHERE user_id=$1", uid)
    un = r["username"] if r else None
    name = (" ".join(x for x in [r["first_name"], r["last_name"]] if x) if r else "") or un or "Пользователь"
    app = app_link(f"n_{un}" if un else f"u_{uid}")
    head = f'<a href="{app}">{esc(name)}</a>' if app else f'<a href="tg://user?id={uid}">{esc(name)}</a>'
    bits = []
    if un:
        bits.append(f'<a href="https://t.me/{un}">@{esc(un)}</a>')
    bits.append(f"ID <code>{uid}</code>")
    bits.append(f"<code>Exg:/{'@' + un if un else 'u' + str(uid)}</code>")
    return head + " · " + " · ".join(bits)


def add_link_buttons(kb, pairs):
    for text, url in pairs:
        if url:
            kb.button(text=text, url=url)


async def notify_staff(text, markup=None):
    if _BOT is None:
        return
    try:
        first, _ = await deliver_card(_BOT, text, markup)
        return first
    except Exception:
        log.exception("notify_staff failed")


async def push_dm(sender_id, peer, post_id, body_txt, fname, fmime):
    """Пуш получателю в Telegram. Не шлём, если он прямо сейчас читает этот чат, и не чаще раза в 40 с на диалог."""
    if _BOT is None:
        return
    if time.monotonic() - _viewing.get((peer, sender_id), 0) < 8:
        return
    try:   # чат «без звука» (форум) — пуш в Telegram не шлём
        if await pool.fetchval("SELECT 1 FROM forum_chat_prefs WHERE user_id=$1 AND peer_id=$2 AND muted", peer, sender_id):
            return
    except Exception:
        pass
    if not rate_ok(("dmpush", peer, sender_id), 40):
        return
    name = await user_name(sender_id)
    msg = f"💬 <b>{esc(name)}</b>" + (f" · объявление #{post_id}" if post_id else "") + f"\n{esc(dm_preview(body_txt, fname, fmime)[:200])}"
    kb = None
    if WEBAPP_URL.startswith("https://"):
        q = f"?chat={sender_id}" + (f"&post={post_id}" if post_id else "")
        bld = InlineKeyboardBuilder()
        bld.button(text="Открыть чат", web_app=WebAppInfo(url=WEBAPP_URL + "/app" + q))
        kb = bld.as_markup()
    try:
        await _BOT.send_message(peer, msg, reply_markup=kb)
    except Exception:
        pass


def share_base():
    if MINIAPP_LINK:
        return MINIAPP_LINK
    if not BOT_USERNAME:
        return ""
    return f"https://t.me/{BOT_USERNAME}" + (f"/{MINIAPP_SHORT}" if MINIAPP_SHORT else "")


async def api_profile(request):
    uid = int(request.query.get("id") or request["u"]["id"])
    row = await pool.fetchrow("""SELECT u.user_id,u.username,u.first_name,u.last_name,u.bio,u.theme,u.accent,u.profile_theme,u.photo_url,
        (u.avatar_data IS NOT NULL) has_avatar, (u.banner_data IS NOT NULL) has_banner, (u.banner_mime LIKE 'video/%') banner_video, u.created_at, u.last_seen,
        COALESCE(avg(r.rating),0)::float rating, count(r.id)::int reviews
        FROM users u LEFT JOIN user_reviews r ON r.target_id=u.user_id
        WHERE u.user_id=$1 GROUP BY u.user_id""", uid)
    if not row:
        raise ApiError(404, "user_not_found")
    deal_rows = await pool.fetch("""SELECT id,amount,status,created_at,buyer_id,seller_id,'guarantor'::text kind FROM escrow_deals
        WHERE buyer_id=$1 OR seller_id=$1
        UNION ALL
        SELECT id,amount,status,created_at,buyer_id,seller_id,'direct'::text kind FROM direct_deals
        WHERE buyer_id=$1 OR seller_id=$1
        ORDER BY created_at DESC LIMIT 30""",uid)
    deals = sum(1 for x in deal_rows if x["status"]=="completed")
    me_id = request["u"]["id"]
    badges = (await user_badges([uid])).get(uid, [])
    bc = (await base_cards([uid])).get(uid)
    base_sum = {"stars": bc["stars"], "score": bc["score"], "label": bc["label"], "status": bc["status"], "tier": bc["tier"], "minus": bc["minus"]} if bc else None
    by_me = by_peer = False
    if uid != me_id:
        by_me, by_peer = await block_state(me_id, uid)
    sb_row = await pool.fetchrow("SELECT badge_dev,badge_adm,badge_badrep,badge_scam FROM users WHERE user_id=$1", uid)
    sb = ("d" if sb_row and sb_row["badge_dev"] else "") + ("a" if sb_row and sb_row["badge_adm"] else "") + ("b" if sb_row and sb_row["badge_badrep"] else "") + ("s" if sb_row and sb_row["badge_scam"] else "")
    flags = None
    if await role(me_id) is not None:
        fr = await pool.fetchrow("SELECT verified,scam FROM users WHERE user_id=$1", uid)
        flags = {"verified": bool(fr["verified"]), "scam": bool(fr["scam"])}
    history=[{"id":x["id"],"amount":x["amount"],"status":x["status"],"created":fmt_dt(x["created_at"]),
        "kind":x["kind"],"side":"Покупатель" if x["buyer_id"]==uid else "Продавец"} for x in deal_rows]
    return jr({"id": row["user_id"], "username": row["username"],
        "name": " ".join(x for x in [row["first_name"],row["last_name"]] if x) or row["username"] or "Пользователь",
        "bio": row["bio"], "theme": row["theme"], "accent": row["accent"], "profile_theme": row["profile_theme"] or "",
        "photo_url": row["photo_url"], "has_avatar": row["has_avatar"], "has_banner": row["has_banner"], "has_banner_video": bool(row["banner_video"]), "created": fmt_dt(row["created_at"]),
        "rating": (bc["score"] if bc else round(row["rating"],1)), "reviews": row["reviews"], "completed_deals": deals, "history": history,
        "badges": badges, "base": base_sum, "blocked_by_me": by_me, "blocked_me": by_peer, "flags": flags,
        "projects": [project_json(x) for x in await pool.fetch(PROJECT_SELECT + " WHERE p.owner_id=$1 ORDER BY p.id", uid)],
        "sb": sb, "can_badge": me_id == OWNER_ID,
        "badge_flags": {"dev": bool(sb_row and sb_row["badge_dev"]), "adm": bool(sb_row and sb_row["badge_adm"]), "bad": bool(sb_row and sb_row["badge_badrep"]), "scam": bool(sb_row and sb_row["badge_scam"])} if me_id == OWNER_ID else None,
        "online": uid == request["u"]["id"] or bool(row["last_seen"] and (datetime.now(timezone.utc) - row["last_seen"]).total_seconds() < 90),
        "is_me": uid == request["u"]["id"]})


async def api_profile_update(request):
    uid=request["u"]["id"]; d=await body(request)
    themes=("dark","light","midnight","ocean","forest","violet","green","blue","pink","mono","lilac","sky")
    sets=[]; args=[uid]
    def add(col,val):
        args.append(val); sets.append(f"{col}=${len(args)}")
    if "bio" in d:
        add("bio",str(d.get("bio") or "").strip()[:500])
    if "theme" in d:
        theme=str(d.get("theme") or "dark")
        if theme not in themes:
            raise ApiError(400,"bad_theme")
        add("theme",theme)
    if "accent" in d:
        accent=str(d.get("accent") or "#8b7cff")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}",accent):
            raise ApiError(400,"bad_accent")
        add("accent",accent)
    if "profile_theme" in d:
        # тема, в которой другие люди видят профиль; пусто = у зрителя своя тема
        pt=str(d.get("profile_theme") or "")
        if pt and pt not in themes:
            raise ApiError(400,"bad_theme")
        add("profile_theme",pt)
    if sets:
        await pool.execute("UPDATE users SET "+",".join(sets)+" WHERE user_id=$1",*args)
    return jr({"ok":True})


BANNER_VIDEO_MAX = 8 * 1024 * 1024


_VIDEO_BAD_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis")


def banner_media(data, mime=None, img_max=6 * 1024 * 1024):
    """Баннер: картинка (JPEG/PNG/WebP) или короткое видео (MP4/WebM до 8 МБ).
    Тип определяем по содержимому файла, а не по заголовку от клиента. Возвращает (data, mime)."""
    if not data:
        raise ApiError(400, "bad_image")
    if data[4:8] == b"ftyp" and data[8:12] not in _VIDEO_BAD_BRANDS:      # MP4 / MOV (H.264)
        if len(data) > BANNER_VIDEO_MAX:
            raise ApiError(400, "bad_video")
        return data, "video/mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":                                  # WebM / Matroska
        if len(data) > BANNER_VIDEO_MAX:
            raise ApiError(400, "bad_video")
        return data, "video/webm"
    if len(data) > img_max or mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ApiError(400, "bad_image")
    return data, mime


async def api_profile_reviews(request):
    uid=int(request.query.get("id") or request["u"]["id"])
    rows=await pool.fetch("""SELECT r.id,r.rating,r.text,r.created_at,r.reviewer_id,(r.photo_data IS NOT NULL) has_photo,
        u.username,u.first_name FROM user_reviews r
        JOIN users u ON u.user_id=r.reviewer_id WHERE r.target_id=$1 ORDER BY r.created_at DESC LIMIT 50""",uid)
    avs=await avatar_info([r["reviewer_id"] for r in rows])
    sbs=await staff_badges([r["reviewer_id"] for r in rows])
    return jr({"reviews":[{"id":r["id"],"rating":r["rating"],"text":r["text"],"author_sb":sbs.get(r["reviewer_id"],""),
        "author_has_avatar":avs.get(r["reviewer_id"],(False,None))[0],
        "author_photo":avs.get(r["reviewer_id"],(False,None))[1],
        "author":r["username"] and "@"+r["username"] or r["first_name"] or "Пользователь",
        "author_id":r["reviewer_id"],
        "photo":img_url("rv",r["id"]) if r["has_photo"] else None,
        "created":fmt_dt(r["created_at"]),"mine":r["reviewer_id"]==request["u"]["id"]} for r in rows]})


async def api_profile_review_save(request):
    uid=request["u"]["id"]
    photo=None; pmime=None
    if (request.content_type or "").startswith("multipart/"):
        form=await request.post(); d={k:form.get(k) for k in ("target_id","rating","text")}
        f=form.get("photo")
        if f is not None and hasattr(f,"file"):
            data=f.file.read(); mime=getattr(f,"content_type",None) or "image/jpeg"
            if data:
                if len(data)>5*1024*1024 or mime not in ("image/jpeg","image/png","image/webp"):
                    raise ApiError(400,"bad_image")
                photo=data; pmime=mime
    else:
        d=await body(request)
    try:
        target=int(d.get("target_id") or 0); rating=int(d.get("rating") or 0)
    except (TypeError, ValueError):
        raise ApiError(400,"bad_review")
    txt=str(d.get("text") or "").strip()[:1000]
    if target==uid or rating not in range(1,6): raise ApiError(400,"bad_review")
    eligible=await pool.fetchval("""SELECT 1 FROM escrow_deals WHERE status='completed'
        AND ((buyer_id=$1 AND seller_id=$2) OR (buyer_id=$2 AND seller_id=$1))
        UNION ALL
        SELECT 1 FROM direct_deals WHERE status='completed'
        AND ((buyer_id=$1 AND seller_id=$2) OR (buyer_id=$2 AND seller_id=$1)) LIMIT 1""",uid,target)
    if not eligible: raise ApiError(403,"review_after_deal_only")
    existed=await pool.fetchval("SELECT id FROM user_reviews WHERE reviewer_id=$1 AND target_id=$2",uid,target)
    deal=await review_deal_info(uid,target)
    rid=await pool.fetchval("""INSERT INTO user_reviews(reviewer_id,target_id,rating,text,photo_data,photo_mime,deal_kind,deal_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT(reviewer_id,target_id) DO UPDATE SET rating=EXCLUDED.rating,text=EXCLUDED.text,
        photo_data=COALESCE(EXCLUDED.photo_data,user_reviews.photo_data),
        photo_mime=COALESCE(EXCLUDED.photo_mime,user_reviews.photo_mime),
        deal_kind=EXCLUDED.deal_kind,deal_id=EXCLUDED.deal_id,updated_at=now() RETURNING id""",
        uid,target,rating,txt,photo,pmime,deal["kind"] if deal else None,deal["id"] if deal else None)
    asyncio.create_task(publish_review(request.app["bot"],rid,edited=bool(existed)))
    return jr({"ok":True})


async def _dm_get(uid, mid):
    """Сообщение, в котором участвует uid (иначе 404)."""
    try: mid=int(mid)
    except (TypeError, ValueError): raise ApiError(400,"bad_id")
    r=await pool.fetchrow("""SELECT id,sender_id,recipient_id,body,deal_id,(file_data IS NOT NULL) has_file
        FROM direct_messages WHERE id=$1 AND (sender_id=$2 OR recipient_id=$2)""",mid,uid)
    if not r: raise ApiError(404,"message_not_found")
    return r


async def api_message_edit(request):
    uid=request["u"]["id"]; d=await body(request)
    r=await _dm_get(uid,d.get("id"))
    if r["sender_id"]!=uid or r["deal_id"]: raise ApiError(403,"forbidden")
    txt=str(d.get("text") or "").strip()
    if len(txt)>3000: raise ApiError(400,"too_long")
    if not txt and not r["has_file"]: raise ApiError(400,"empty")
    peer=r["recipient_id"]
    await need_not_blocked(uid,peer)
    if txt!=r["body"]:
        await pool.execute("UPDATE direct_messages SET body=$2,edited_at=now() WHERE id=$1",r["id"],txt)
    return jr({"ok":True})


async def api_message_delete(request):
    uid=request["u"]["id"]; d=await body(request)
    ids=d.get("ids") if isinstance(d.get("ids"),list) else [d.get("id")]
    for_all=bool(d.get("for_all"))
    for mid in ids[:50]:
        r=await _dm_get(uid,mid)
        if r["deal_id"]: continue
        if for_all and r["sender_id"]==uid:
            await pool.execute("DELETE FROM direct_messages WHERE id=$1",r["id"])
            await pool.execute("DELETE FROM dm_hidden WHERE msg_id=$1",r["id"])
        else:
            await pool.execute("INSERT INTO dm_hidden(user_id,msg_id) VALUES($1,$2) ON CONFLICT DO NOTHING",uid,r["id"])
    return jr({"ok":True})


async def api_message_pin(request):
    uid=request["u"]["id"]; d=await body(request)
    r=await _dm_get(uid,d.get("id"))
    if r["deal_id"]: raise ApiError(403,"forbidden")
    if d.get("pin",True):
        await pool.execute("UPDATE direct_messages SET pinned_at=now() WHERE id=$1",r["id"])
    else:
        await pool.execute("UPDATE direct_messages SET pinned_at=NULL WHERE id=$1",r["id"])
    return jr({"ok":True})


async def api_message_forward(request):
    uid=request["u"]["id"]; d=await body(request)
    try: to=int(d.get("to") or 0)
    except (TypeError, ValueError): raise ApiError(400,"bad_peer")
    ids=d.get("ids") if isinstance(d.get("ids"),list) else [d.get("id")]
    if not to or to==uid or not ids: raise ApiError(400,"bad_peer")
    if not await pool.fetchval("SELECT 1 FROM users WHERE user_id=$1",to): raise ApiError(404,"user_not_found")
    await need_not_blocked(uid,to)
    n=0; last=None
    for mid in sorted({int(x) for x in ids[:20] if str(x).isdigit()}):
        r=await _dm_get(uid,mid)
        if r["deal_id"]: continue
        await pool.execute("""INSERT INTO direct_messages(sender_id,recipient_id,body,file_data,file_mime,file_name,file_size,fwd_from,voice_dur,voice_wave)
            SELECT $1,$2,body,file_data,file_mime,file_name,file_size,COALESCE(fwd_from,sender_id),voice_dur,voice_wave FROM direct_messages WHERE id=$3""",uid,to,r["id"])
        n+=1; last=r
    if n:
        asyncio.create_task(push_dm(uid,to,None,"↪️ Пересланное сообщение" if n==1 and not (last["body"] or "") else (last["body"] or "↪️ Пересланное сообщение"),None,None))
    return jr({"ok":True,"count":n})


async def api_block(request):
    uid=request["u"]["id"]; d=await body(request)
    target=int(d.get("user_id") or 0)
    if not target or target==uid: raise ApiError(400,"bad_input")
    if d.get("block",True):
        await pool.execute("INSERT INTO user_blocks(blocker_id,blocked_id) VALUES($1,$2) ON CONFLICT DO NOTHING",uid,target)
    else:
        await pool.execute("DELETE FROM user_blocks WHERE blocker_id=$1 AND blocked_id=$2",uid,target)
    return jr({"ok":True})


async def api_blocks(request):
    uid=request["u"]["id"]
    rows=await pool.fetch("""SELECT u.user_id,u.username,u.first_name,u.last_name FROM user_blocks b
        JOIN users u ON u.user_id=b.blocked_id WHERE b.blocker_id=$1 ORDER BY b.created_at DESC""",uid)
    return jr({"users":[{"id":r["user_id"],"name":" ".join(x for x in [r["first_name"],r["last_name"]] if x) or r["username"] or "Пользователь"} for r in rows]})


MAX_REPORT_PHOTOS = 5


async def api_report_user(request):
    uid=request["u"]["id"]
    files=[]
    if (request.content_type or "").startswith("multipart/"):
        form=await request.post()
        d={k:form.get(k) for k in ("user_id","post_id","category","reason")}
        for f in form.getall("photo",[]):
            if not hasattr(f,"file"): continue
            data=f.file.read(); mime=getattr(f,"content_type",None) or "image/jpeg"
            if not data: continue
            if len(data)>5*1024*1024 or mime not in IMG_MIMES: raise ApiError(400,"bad_image")
            files.append((bytes(data),mime))
        if len(files)>MAX_REPORT_PHOTOS: raise ApiError(400,"too_many_photos")
    else:
        d=await body(request)
    try:
        target=int(d.get("user_id") or 0); post_id=int(d.get("post_id") or 0) or None
    except (TypeError, ValueError):
        raise ApiError(400,"bad_input")
    cat=str(d.get("category") or "").strip(); cat=cat if cat in BASE_REPORT_CATS else None
    reason=(d.get("reason") or "Жалоба на пользователя").strip()[:500]
    if not target or target==uid: raise ApiError(400,"bad_input")
    if not rate_ok(("urep",uid),4): raise ApiError(429,"slow")
    if not await pool.fetchval("SELECT 1 FROM users WHERE user_id=$1",target): raise ApiError(404,"user_not_found")
    row=await pool.fetchrow("INSERT INTO user_reports(target_id,reporter_id,post_id,reason,category) VALUES($1,$2,$3,$4,$5) "
        "ON CONFLICT(target_id,reporter_id) DO NOTHING RETURNING id",target,uid,post_id,reason,cat)
    if row:
        for i,(data,mime) in enumerate(files):
            await pool.execute("INSERT INTO report_photos(report_id,pos,data,mime) VALUES($1,$2,$3,$4)",row["id"],i,data,mime)
        kb=InlineKeyboardBuilder()
        kb.button(text="🚫 Мошенник",callback_data=f"ur:scam:{row['id']}")
        kb.button(text="✅ Закрыть",callback_data=f"ur:ok:{row['id']}")
        kb.button(text="🗑 Удалить полностью",callback_data=f"ur:del:{row['id']}")
        tun=await pool.fetchval("SELECT username FROM users WHERE user_id=$1",target)
        add_link_buttons(kb,[("👤 Профиль",app_link(f"n_{tun}" if tun else f"u_{target}")),
                             ("📖 В VETRIXBASE",app_link(f"b_{target}")),
                             ("📄 Объявление",app_link(f"ad_{post_id}") if post_id else "")])
        kb.adjust(2,1,2,1)
        text=(f"🚩 <b>Жалоба #{row['id']} на пользователя</b>\n"
            f"На: {await who_html(target)}\n"
            f"От: {await who_html(uid)}\n"
            + (f"Категория: <b>{esc(cat)}</b>\n" if cat else "") + f"Причина: {esc(reason)}"
            + (f"\n📎 Доказательства: {len(files)} скрин." if files else "")
            + (f"\nОбъявление: #{post_id} · <code>Exg:/a{post_id}</code>" + (f' · <a href="{app_link(f"ad_{post_id}")}">открыть</a>' if app_link(f"ad_{post_id}") else "") if post_id else ""))

        async def notify():
            first=await notify_staff(text, kb.as_markup())
            if first is not None and files and _BOT is not None:
                try:
                    media=[InputMediaPhoto(media=BufferedInputFile(data,filename=f"proof{i+1}.jpg")) for i,(data,_) in enumerate(files)]
                    await _BOT.send_media_group(first.chat.id,media,reply_parameters=ReplyParameters(message_id=first.message_id,allow_sending_without_reply=True))
                except Exception:
                    log.exception("report proofs to staff failed")
        asyncio.create_task(notify())
        n=await pool.fetchval("SELECT count(DISTINCT reporter_id) FROM user_reports WHERE target_id=$1 AND status='new'",target)
        if n==BASE_MINUS_REPORTS:
            asyncio.create_task(notify_staff(
                f"⛔ <b>В VETRIXBASE новый минус:</b> {await who_html(target)}\n"
                f"Набралось {n} активных жалоб — человек помечен как «Ненадёжный». Если жалобы необоснованны — закройте их («✅ Закрыть») или удалите, и метка снимется."))
    return jr({"ok":True,"duplicate":row is None})


async def api_admin_user_flag(request):
    await need_main(request)
    d=await body(request); target=int(d.get("user_id") or 0); flag=str(d.get("flag") or "")
    if not await pool.fetchval("SELECT 1 FROM users WHERE user_id=$1",target): raise ApiError(404,"user_not_found")
    if flag=="verified": await pool.execute("UPDATE users SET verified=TRUE,scam=FALSE WHERE user_id=$1",target)
    elif flag=="scam": await pool.execute("UPDATE users SET scam=TRUE,verified=FALSE WHERE user_id=$1",target)
    elif flag=="clear":
        await pool.execute("UPDATE users SET scam=FALSE,verified=FALSE WHERE user_id=$1",target)
        await pool.execute("UPDATE user_reports SET status='reviewed' WHERE target_id=$1",target)
    else: raise ApiError(400,"bad_input")
    return jr({"ok":True})


async def api_admin_user_badge(request):
    """Только владелец (OWNER_ID из окружения): выдать/снять значок «разработчик» (dev), «админ» (adm), плашку «BAD REP» (bad) и/или «SCAM» (scam) — в любом сочетании."""
    if request["u"]["id"] != OWNER_ID: raise ApiError(403,"forbidden")
    d=await body(request); target=int(d.get("user_id") or 0); badge=str(d.get("badge") or ""); on=bool(d.get("on"))
    col={"dev":"badge_dev","adm":"badge_adm","bad":"badge_badrep","scam":"badge_scam"}.get(badge)
    if not col: raise ApiError(400,"bad_input")
    if not await pool.fetchval("SELECT 1 FROM users WHERE user_id=$1",target): raise ApiError(404,"user_not_found")
    await pool.execute(f"UPDATE users SET {col}=$2 WHERE user_id=$1",target,on)
    return jr({"ok":True})


PROJECT_SELECT = ("SELECT p.id,p.owner_id,p.kind,p.name,p.username,p.link,p.description,p.verified,p.mark,p.mark_req,p.created_at,"
                  "(p.avatar_data IS NOT NULL) has_avatar,(p.banner_data IS NOT NULL) has_banner,"
                  "COALESCE((SELECT avg(rating) FROM project_reviews WHERE project_id=p.id),0)::float rating,"
                  "(SELECT count(*) FROM project_reviews WHERE project_id=p.id)::int reviews FROM projects p")


def project_url(p):
    return f"https://t.me/{p['username']}" if p["username"] else (p["link"] or None)


def project_json(p):
    return {"id": p["id"], "owner_id": p["owner_id"], "kind": p["kind"], "name": p["name"], "username": p["username"],
            "link": p["link"], "url": project_url(p), "description": p["description"], "verified": bool(p["mark"]), "mark": p["mark"], "mark_req": p["mark_req"],
            "has_avatar": p["has_avatar"], "created": fmt_dt(p["created_at"]),
            "has_banner": bool(p.get("has_banner")), "rating": round(float(p.get("rating") or 0), 1), "reviews": int(p.get("reviews") or 0)}


async def direct_member(deal_id, uid):
    row = await pool.fetchrow("SELECT * FROM direct_deals WHERE id=$1 AND (buyer_id=$2 OR seller_id=$2)", deal_id, uid)
    if not row:
        raise ApiError(404, "direct_deal_not_found")
    return row


async def api_report_any(request):
    """Жалоба на отзыв или сделку — уходит в админ-чат со ссылками на профили и на отзыв."""
    uid = request["u"]["id"]; d = await body(request)
    kind = str(d.get("kind") or ""); ref = int(d.get("id") or 0)
    reason = (d.get("reason") or "Жалоба из мини-приложения").strip()[:500]
    if kind not in ("review", "deal") or ref <= 0: raise ApiError(400, "bad_input")
    target = None; lines = ""; buttons = []; acts = []
    if kind == "review":
        rv = await pool.fetchrow("SELECT reviewer_id,target_id,rating,text FROM user_reviews WHERE id=$1", ref)
        if not rv: raise ApiError(404, "review_not_found")
        target = rv["reviewer_id"]
        lines = (f"Отзыв: {'★' * rv['rating']}{'☆' * (5 - rv['rating'])} · <code>Exg:/r{ref}</code>"
                 + (f' · <a href="{app_link(f"r_{ref}")}">открыть</a>' if app_link(f"r_{ref}") else "") + "\n"
                 f"Автор отзыва: {await who_html(rv['reviewer_id'])}\nО пользователе: {await who_html(rv['target_id'])}\n"
                 f"Текст: {esc((rv['text'] or '—')[:400])}\n")
        buttons = [("⭐ Отзыв", app_link(f"r_{ref}"))]
        acts = [("🗑 Удалить отзыв", "delrev")]
    else:
        dl = await direct_member(ref, uid)
        target = dl["seller_id"] if uid == dl["buyer_id"] else dl["buyer_id"]
        lines = (f"Сделка #{ref} · <code>Exg:/d{ref}</code> · статус: {esc(dl['status'])} · сумма: {int(dl['amount'] or 0)} ⭐\n"
                 f"Покупатель: {await who_html(dl['buyer_id'])}\nПродавец: {await who_html(dl['seller_id'])}\n"
                 f"Условия: {esc((dl['terms'] or '')[:500])}\n")
        acts = [("🚫 Мошенник", "scam")]
    row = await pool.fetchrow("INSERT INTO misc_reports(kind,ref_id,reporter_id,target_id,reason) VALUES($1,$2,$3,$4,$5) "
        "ON CONFLICT(kind,ref_id,reporter_id) DO NOTHING RETURNING id", kind, ref, uid, target, reason)
    if row:
        kb = InlineKeyboardBuilder()
        for t, a in acts: kb.button(text=t, callback_data=f"mr:{a}:{row['id']}")
        kb.button(text="✅ Закрыть", callback_data=f"mr:ok:{row['id']}")
        if target:
            tun = await pool.fetchval("SELECT username FROM users WHERE user_id=$1", target)
            buttons.append(("👤 Профиль", app_link(f"n_{tun}" if tun else f"u_{target}")))
        add_link_buttons(kb, buttons); kb.adjust(2, 2)
        title = "на отзыв" if kind == "review" else "на сделку"
        asyncio.create_task(notify_staff(
            f"🚩 <b>Жалоба #{row['id']} {title}</b>\nОт: {await who_html(uid)}\nПричина: {esc(reason)}\n\n{lines}", kb.as_markup()))
    return jr({"ok": True, "duplicate": row is None})



# ---------------------------------------------------------------- инициализация (вместо init_db() из bot.py)
async def init_pool():
    """Подключение к ТОЙ ЖЕ базе, что и у бота (таблицы users, direct_messages и т.д. создаёт бот)."""
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, statement_cache_size=0, init=_init_conn)
    return pool
