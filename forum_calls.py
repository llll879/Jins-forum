# -*- coding: utf-8 -*-
"""
KMBP FORUM — звонки: личные и групповые (аудио/видео, WebRTC).

Сервер здесь только «сигнальный»: звук и видео идут напрямую между участниками (mesh), через STUN/TURN.
  • Один постоянный long-poll  GET /forum/api/calls/poll  на пользователя: входящие вызовы + сообщения сигнализации.
    (Без WebSocket: работает через тот же Bearer-токен, CORS и APK-конвертеры, что и остальной API.)
  • Состояние звонков хранится в памяти процесса (звонок живёт минуты — БД не нужна, миграций нет).
  • Личный звонок = звонок из двух человек, в него можно добавлять людей (invite) — он становится групповым.
  • Групповой звонок в чате-группе: любой участник нажимает «позвонить», остальные видят плашку «Идёт звонок» и
    могут присоединиться. В звонок можно позвать и тех, кто не состоит в группе.
  • В конце звонка в чат пишется запись: «📞 Звонок · 3:21» / «Пропущенный звонок» / «Групповой звонок · 12:05».

Настройка (все переменные необязательные):
  CALL_MAX          — максимум участников (по умолчанию 8; mesh: каждый шлёт видео каждому)
  CALL_STUN         — STUN через запятую (по умолчанию серверы Google)
  CALL_TURN_URLS    — TURN через запятую, напр. turn:turn.example.com:3478,turns:turn.example.com:5349
  CALL_TURN_USER / CALL_TURN_PASS — постоянные данные TURN
  CALL_TURN_SECRET  — вместо USER/PASS: секрет coturn (use-auth-secret), выдаются временные пароли
  CALL_TURN_PUBLIC  — 0, чтобы отключить публичный тестовый TURN (Open Relay), который подставляется, если свой не задан
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import deque

from aiohttp import web

import forum as F
from forum import FErr, J, api, jbody, to_int, users_map

log = logging.getLogger("jins.calls")
P = F.P


def _env_int(name, default):
    try:
        return max(2, int(os.getenv(name, "") or default))
    except ValueError:
        return default


MAX_PARTS = _env_int("CALL_MAX", 8)
RING_SEC = 45           # сколько звонит вызов
POLL_SEC = 20           # длина одного long-poll
STALE_SEC = 40          # участник без опроса дольше этого считается вышедшим
RING_GROUP_MAX = 30     # в группах больше этого размера звонок не «трезвонит» всем, а только показывает плашку
ALONE_SEC = 900         # групповой звонок, где остался один человек, закрывается через 15 минут
SIG_MAX = 24000         # максимальный размер одного сигнального сообщения (SDP + ICE)

BOOT = secrets.token_hex(4)     # меняется при перезапуске сервера: клиент понимает, что звонки сброшены
CALLS: dict = {}                # id -> звонок
IN_CALL: dict = {}              # user_id -> id звонка, в котором он участвует
BOX: dict = {}                  # user_id -> почтовый ящик событий
_task = None


# ============================================================================ почтовые ящики
class Box:
    __slots__ = ("seq", "q", "ev", "seen")

    def __init__(self):
        self.seq = 0
        self.q = deque(maxlen=400)
        self.ev = asyncio.Event()
        self.seen = time.monotonic()


def box(uid) -> Box:
    b = BOX.get(uid)
    if b is None:
        b = BOX[uid] = Box()
    return b


def push(uid, ev):
    b = box(uid)
    b.seq += 1
    b.q.append(dict(ev, seq=b.seq))
    b.ev.set()


def online(uid, within=25):
    b = BOX.get(uid)
    return bool(b and time.monotonic() - b.seen < within)


# ============================================================================ вспомогательное
def short(u):
    return {"id": u["id"], "name": u["name"], "username": u["username"], "av": u["av"], "sb": u["sb"]}


async def users_short(ids):
    um = await users_map(list(ids))
    return {i: short(um.get(i) or F.ghost(i)) for i in ids}


def ice_servers(uid):
    stun = [u.strip() for u in (os.getenv("CALL_STUN") or "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302").split(",") if u.strip()]
    out = [{"urls": stun}]
    turn = [u.strip() for u in (os.getenv("CALL_TURN_URLS") or "").split(",") if u.strip()]
    if turn:
        secret = os.getenv("CALL_TURN_SECRET") or ""
        if secret:
            user = f"{int(time.time()) + 6 * 3600}:{uid}"
            cred = base64.b64encode(hmac.new(secret.encode(), user.encode(), hashlib.sha1).digest()).decode()
        else:
            user, cred = os.getenv("CALL_TURN_USER") or "", os.getenv("CALL_TURN_PASS") or ""
        out.append({"urls": turn, "username": user, "credential": cred})
    elif (os.getenv("CALL_TURN_PUBLIC") or "1") != "0":
        # публичный тестовый TURN (Open Relay): нужен, чтобы звонки шли через мобильный интернет и строгие NAT.
        # Для постоянной работы задайте свой TURN (CALL_TURN_URLS) — публичный бесплатен, но ограничен по трафику.
        out.append({"urls": ["turn:openrelay.metered.ca:80", "turn:openrelay.metered.ca:443", "turn:openrelay.metered.ca:443?transport=tcp"],
                    "username": "openrelayproject", "credential": "openrelayproject"})
    return out


async def call_state(c):
    ids = set(c["parts"]) | set(c["inv"])
    us = await users_short(ids)
    return {
        "id": c["id"], "kind": c["kind"], "gid": c["gid"], "title": c["title"], "video": c["video"], "host": c["host"],
        "max": MAX_PARTS, "answered": bool(c["answered"]), "t0": c["answered"] or c["created"],
        "parts": [{"user": us[u], "muted": p["muted"], "video": p["video"], "screen": p["screen"]} for u, p in c["parts"].items()],
        "inv": [us[u] for u in c["inv"]],
    }


def ringing_for(uid):
    now = time.monotonic()
    out = []
    for c in CALLS.values():
        i = c["inv"].get(uid)
        if i:
            out.append({"call": c["id"], "kind": c["kind"], "gid": c["gid"], "title": c["title"], "video": c["video"], "by": i["by"],
                        "left": max(0, int(RING_SEC - (now - i["t"])))})
    return out


def get_call(cid, need=True):
    c = CALLS.get(str(cid or ""))
    if not c and need:
        raise FErr(404, "call_gone", "Звонок уже завершён")
    return c


async def is_member(gid, uid):
    return bool(await P().fetchval("SELECT 1 FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, uid))


async def can_talk(a, b):
    by_me, by_peer = await F.bm.block_state(a, b)
    return not (by_me or by_peer)


def new_call(kind, host, video, gid=0, title=""):
    c = {"id": secrets.token_urlsafe(9), "kind": kind, "gid": gid, "title": title, "video": bool(video), "host": host, "peer": 0,
         "created": time.time(), "answered": 0, "parts": {}, "inv": {}, "why": "", "alone": 0}
    CALLS[c["id"]] = c
    return c


def add_part(c, uid, video=False):
    c["parts"][uid] = {"muted": False, "video": bool(video), "screen": False, "t": time.time()}
    IN_CALL[uid] = c["id"]
    if not c["answered"] and len(c["parts"]) >= 2:
        c["answered"] = time.time()


def ring(c, uid, by):
    c["inv"][uid] = {"t": time.monotonic(), "by": by}
    push(uid, {"t": "ring", "call": c["id"]})


async def tg_push(to, who_id, c):
    """Звонок тому, кто сейчас не в приложении: сообщение от бота с кнопкой «Открыть» (как остальные уведомления форума)."""
    bm = F.bm
    try:
        if not (bm._BOT and bm.WEBAPP_URL and bm.rate_ok(("fcallpush", to), 45)):
            return
        if not (await F.get_prefs(to)).get("tg", True):
            return
        who = await bm.user_name(who_id)
        what = "звонит вам" if c["kind"] == "dm" else "зовёт вас в звонок"
        if c["title"]:
            what += " «%s»" % bm.esc(c["title"][:40])
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        link = f"{bm.WEBAPP_URL}/forum"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть", web_app=WebAppInfo(url=link))]]) if link.startswith("https://") else None
        await bm._BOT.send_message(to, f"{'📹' if c['video'] else '📞'} <b>KMBP FORUM</b>\n{bm.esc(who)} {what}.", reply_markup=kb)
    except Exception:
        pass


async def tg_missed(to, who_id, video):
    bm = F.bm
    try:
        if not (bm._BOT and bm.WEBAPP_URL and bm.rate_ok(("fcallmiss", to), 30)):
            return
        if not (await F.get_prefs(to)).get("tg", True):
            return
        who = await bm.user_name(who_id)
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        link = f"{bm.WEBAPP_URL}/forum#/c/{who_id}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть чат", web_app=WebAppInfo(url=link))]]) if link.startswith("https://") else None
        await bm._BOT.send_message(to, f"📵 <b>KMBP FORUM</b>\nПропущенный {'видеозвонок' if video else 'звонок'} от {bm.esc(who)}.", reply_markup=kb)
    except Exception:
        pass


async def gcast(c, ended=False):
    """Плашка «Идёт звонок» у участников группы, которые сейчас онлайн."""
    if c["kind"] != "group" or not c["gid"]:
        return
    now = time.monotonic()
    on = [u for u, b in BOX.items() if now - b.seen < 60]
    if not on:
        return
    rows = await P().fetch("SELECT user_id FROM forum_group_members WHERE group_id=$1 AND user_id=ANY($2::bigint[])", c["gid"], on)
    ids = list(c["parts"])[:3]
    us = await users_short(ids) if ids and not ended else {}
    ev = {"t": "gcall", "group": c["gid"], "call": None if ended else c["id"], "n": len(c["parts"]), "video": c["video"], "users": [us[i] for i in ids if i in us]}
    for r in rows:
        push(r["user_id"], ev)


def _dur(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


async def write_log(c, reason):
    """Запись о звонке в чат (личный или групповой)."""
    try:
        dur = time.time() - c["answered"] if c["answered"] else 0
        if c["kind"] == "dm" and c["peer"]:
            ico = "📹" if c["video"] else "📞"
            if c["answered"]:
                body = f"{ico} {'Видеозвонок' if c['video'] else 'Звонок'} · {_dur(dur)}"
            elif reason == "declined":
                body = f"{ico} Звонок отклонён"
            elif reason == "cancel":
                body = f"{ico} Отменённый звонок"
            else:
                body = f"{ico} Пропущенный звонок"
            await P().execute("INSERT INTO direct_messages(sender_id,recipient_id,body) VALUES($1,$2,$3)", c["host"], c["peer"], body)
            if not c["answered"] and reason in ("timeout", "busy"):
                await tg_missed(c["peer"], c["host"], c["video"])
        elif c["kind"] == "group" and c["gid"] and c["answered"] and dur >= 5:
            await P().execute("INSERT INTO forum_group_msgs(group_id,sender_id,body) VALUES($1,$2,$3)", c["gid"], c["host"],
                              f"{'📹 Групповой видеозвонок' if c['video'] else '📞 Групповой звонок'} · {_dur(dur)}")
    except Exception:
        log.exception("call log failed")


async def end_call(c, reason):
    if CALLS.pop(c["id"], None) is None:
        return
    for u in list(c["parts"]):
        if IN_CALL.get(u) == c["id"]:
            IN_CALL.pop(u, None)
        push(u, {"t": "end", "call": c["id"], "reason": reason})
    for u in list(c["inv"]):
        push(u, {"t": "ring_end", "call": c["id"]})
    c["parts"].clear()
    c["inv"].clear()
    await gcast(c, ended=True)
    await write_log(c, reason)


async def maybe_end(c, reason):
    """Звонок закрывается, когда в нём никого нет, а личный — когда остался один и никого не вызывают."""
    if c["id"] not in CALLS:
        return
    n, inv = len(c["parts"]), len(c["inv"])
    if n == 0 or (c["kind"] == "dm" and n <= 1 and inv == 0):
        await end_call(c, c["why"] or reason)
    else:
        await gcast(c)


async def drop_part(c, uid, reason):
    if uid not in c["parts"]:
        return
    c["parts"].pop(uid, None)
    if IN_CALL.get(uid) == c["id"]:
        IN_CALL.pop(uid, None)
    for u in c["parts"]:
        push(u, {"t": "left", "call": c["id"], "uid": uid, "reason": reason})


# ============================================================================ API
@api
async def a_poll(request):
    me = request["fuid"]
    b = box(me)
    b.seen = time.monotonic()
    try:
        after = int(request.query.get("after", "0"))
    except ValueError:
        after = 0
    first = after < 0                      # первый опрос после запуска: только текущее состояние, без «старых» событий
    if after > b.seq:
        after = 0                          # сервер перезапускался
    end = time.monotonic() + POLL_SEC
    evs = []
    while True:
        if first:
            break
        evs = [e for e in b.q if e["seq"] > after]
        left = end - time.monotonic()
        if evs or left <= 0:
            break
        b.ev.clear()
        try:
            await asyncio.wait_for(b.ev.wait(), timeout=left)
        except asyncio.TimeoutError:
            pass
        b.seen = time.monotonic()
    rg = ringing_for(me)
    if rg:
        us = await users_short({r["by"] for r in rg})
        for r in rg:
            r["by"] = us.get(r["by"])
    return J({"boot": BOOT, "seq": b.seq, "events": evs, "ringing": rg, "mine": IN_CALL.get(me) or ""})


@api
async def a_ice(request):
    return J({"ice": ice_servers(request["fuid"])})


@api
async def a_start(request):
    me = request["fuid"]
    d = await jbody(request)
    video = bool(d.get("video"))
    if not F.bm.rate_ok(("fcall", me), 1.5):
        raise FErr(429, "too_fast", "Не так быстро")
    if IN_CALL.get(me):
        raise FErr(409, "in_call", "Вы уже в звонке")
    gid, peer = to_int(d.get("group")), to_int(d.get("peer"))
    if gid:
        import forum_groups
        cx = await forum_groups.ctx(me, gid, "member")
        if cx.channel:
            raise FErr(400, "channel", "В каналах звонки недоступны")
        for c in CALLS.values():                          # звонок в этой группе уже идёт — просто присоединяемся
            if c["kind"] == "group" and c["gid"] == gid:
                return await _do_join(me, c, video)
        c = new_call("group", me, video, gid, cx.g["title"])
        add_part(c, me, video)
        n = await P().fetchval("SELECT count(*) FROM forum_group_members WHERE group_id=$1", gid)
        if n <= RING_GROUP_MAX:
            rows = await P().fetch("SELECT user_id FROM forum_group_members WHERE group_id=$1 AND user_id<>$2 AND NOT muted", gid, me)
            for r in rows:
                u = r["user_id"]
                if not IN_CALL.get(u) and await can_talk(me, u):
                    ring(c, u, me)
                    if not online(u):
                        asyncio.create_task(tg_push(u, me, c))
        await gcast(c)
    elif peer:
        from support import SUPPORT_ID
        if peer == me or peer == SUPPORT_ID or not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1 AND user_id>0", peer):
            raise FErr(400, "bad_peer", "Этому пользователю позвонить нельзя")
        if not await can_talk(me, peer):
            raise FErr(403, "blocked", "Звонок недоступен (блокировка)")
        if IN_CALL.get(peer):
            raise FErr(409, "busy", "Абонент сейчас занят")
        c = new_call("dm", me, video)
        c["peer"] = peer
        add_part(c, me, video)
        ring(c, peer, me)
        if not online(peer):
            asyncio.create_task(tg_push(peer, me, c))
    else:
        raise FErr(400, "bad_input", "Неверные данные")
    return J({"call": await call_state(c), "ice": ice_servers(me), "peers": [], "boot": BOOT, "seq": box(me).seq})


async def _do_join(me, c, video):
    if IN_CALL.get(me) and IN_CALL[me] != c["id"]:
        raise FErr(409, "in_call", "Вы уже в другом звонке")
    allowed = me in c["parts"] or me in c["inv"] or (c["kind"] == "group" and await is_member(c["gid"], me))
    if not allowed:
        raise FErr(403, "forbidden", "Вас не приглашали в этот звонок")
    if me not in c["parts"] and len(c["parts"]) >= MAX_PARTS:
        raise FErr(409, "full", "В звонке уже максимум участников (%d)" % MAX_PARTS)
    if me in c["parts"]:                                   # перезаход (перезагрузили страницу): остальные сбросят старое соединение
        await drop_part(c, me, "rejoin")
    existing = list(c["parts"])
    add_part(c, me, video)
    c["inv"].pop(me, None)
    c["alone"] = 0
    us = await users_short([me])
    for u in existing:
        push(u, {"t": "joined", "call": c["id"], "user": us[me], "video": bool(video)})
    push(me, {"t": "ring_end", "call": c["id"]})           # погасить вызов на других вкладках
    await gcast(c)
    return J({"call": await call_state(c), "ice": ice_servers(me), "peers": existing, "boot": BOOT, "seq": box(me).seq})


@api
async def a_join(request):
    me = request["fuid"]
    d = await jbody(request)
    return await _do_join(me, get_call(d.get("call")), bool(d.get("video")))


@api
async def a_decline(request):
    me = request["fuid"]
    d = await jbody(request)
    c = get_call(d.get("call"), need=False)
    if not c or me not in c["inv"]:
        return J({"ok": True})
    c["inv"].pop(me, None)
    push(me, {"t": "ring_end", "call": c["id"]})
    if c["kind"] == "dm" and me == c["peer"] and not c["answered"]:
        c["why"] = "declined"
    for u in c["parts"]:
        push(u, {"t": "declined", "call": c["id"], "uid": me})
    await maybe_end(c, "declined")
    return J({"ok": True})


@api
async def a_leave(request):
    me = request["fuid"]
    d = await jbody(request)
    c = get_call(d.get("call"), need=False)
    if not c:
        return J({"ok": True})
    if me in c["parts"]:
        if c["kind"] == "dm" and me == c["host"] and not c["answered"]:
            c["why"] = "cancel"
        await drop_part(c, me, "left")
        await maybe_end(c, "hangup")
    elif me in c["inv"]:
        c["inv"].pop(me, None)
        push(me, {"t": "ring_end", "call": c["id"]})
        await maybe_end(c, "declined")
    return J({"ok": True})


@api
async def a_invite(request):
    """Позвать в идущий звонок людей (в том числе не из группы). Звать может любой участник."""
    me = request["fuid"]
    d = await jbody(request)
    c = get_call(d.get("call"))
    if me not in c["parts"]:
        raise FErr(403, "forbidden", "Вы не в этом звонке")
    if not F.bm.rate_ok(("fcallinv", me), 1):
        raise FErr(429, "too_fast", "Не так быстро")
    raw = d.get("user_ids") if isinstance(d.get("user_ids"), list) else []
    ids = [i for i in dict.fromkeys(to_int(x) for x in raw[:20] if isinstance(x, (int, str))) if i and i != me]
    out = {"invited": [], "busy": [], "blocked": [], "full": [], "bad": []}
    for u in ids:
        if u in c["parts"]:
            continue
        if u in c["inv"]:
            out["invited"].append(u)
            continue
        if len(c["parts"]) + len(c["inv"]) >= MAX_PARTS:
            out["full"].append(u)
            continue
        from support import SUPPORT_ID
        if u == SUPPORT_ID or not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1 AND user_id>0", u):
            out["bad"].append(u)
            continue
        if not await can_talk(me, u):
            out["blocked"].append(u)
            continue
        if IN_CALL.get(u):
            out["busy"].append(u)
            continue
        ring(c, u, me)
        out["invited"].append(u)
        if not online(u):
            asyncio.create_task(tg_push(u, me, c))
    if out["invited"]:
        us = await users_short(out["invited"])
        for p in c["parts"]:
            push(p, {"t": "invited", "call": c["id"], "users": [us[i] for i in out["invited"]]})
    return J(out)


@api
async def a_sig(request):
    """Сообщения WebRTC (offer / answer / ICE) от участника к участнику. Можно пачкой: items=[...]."""
    me = request["fuid"]
    d = await jbody(request)
    c = get_call(d.get("call"), need=False)
    to = to_int(d.get("to"))
    if not c or me not in c["parts"] or to not in c["parts"] or to == me:
        return J({"ok": False})
    items = d.get("items") if isinstance(d.get("items"), list) else [d.get("data")]
    for it in items[:40]:
        if not isinstance(it, dict):
            continue
        if len(json.dumps(it, ensure_ascii=False)) > SIG_MAX:
            continue
        push(to, {"t": "sig", "call": c["id"], "from": me, "data": it})
    return J({"ok": True})


@api
async def a_state(request):
    """Микрофон / камера / показ экрана — чтобы у других отображались значки."""
    me = request["fuid"]
    d = await jbody(request)
    c = get_call(d.get("call"), need=False)
    if not c or me not in c["parts"]:
        return J({"ok": False})
    p = c["parts"][me]
    for k in ("muted", "video", "screen"):
        if k in d:
            p[k] = bool(d[k])
    for u in c["parts"]:
        if u != me:
            push(u, {"t": "state", "call": c["id"], "uid": me, "muted": p["muted"], "video": p["video"], "screen": p["screen"]})
    return J({"ok": True})


@api
async def a_active(request):
    """Идёт ли звонок в группе (для плашки «Присоединиться»)."""
    me = request["fuid"]
    gid = to_int(request.query.get("group"))
    import forum_groups
    await forum_groups.ctx(me, gid, "member")
    for c in CALLS.values():
        if c["kind"] == "group" and c["gid"] == gid:
            ids = list(c["parts"])[:3]
            us = await users_short(ids)
            return J({"call": {"id": c["id"], "n": len(c["parts"]), "video": c["video"], "users": [us[i] for i in ids]}})
    return J({"call": None})


# ============================================================================ фоновая уборка
async def sweep():
    now = time.monotonic()
    for c in list(CALLS.values()):
        if c["id"] not in CALLS:
            continue
        for u, i in list(c["inv"].items()):               # никто не ответил
            if now - i["t"] > RING_SEC:
                c["inv"].pop(u, None)
                push(u, {"t": "ring_end", "call": c["id"]})
                for p in c["parts"]:
                    push(p, {"t": "noanswer", "call": c["id"], "uid": u})
                if c["kind"] == "dm" and u == c["peer"] and not c["answered"]:
                    c["why"] = "timeout"
        for u in list(c["parts"]):                         # вкладку закрыли / пропал интернет
            b = BOX.get(u)
            if not b or now - b.seen > STALE_SEC:
                await drop_part(c, u, "lost")
        if c["id"] not in CALLS:
            continue
        if len(c["parts"]) == 1 and not c["inv"] and c["kind"] == "group":
            c["alone"] = c["alone"] or now
            if now - c["alone"] > ALONE_SEC:
                await end_call(c, "alone")
                continue
        else:
            c["alone"] = 0
        await maybe_end(c, "timeout")
    for u in [u for u, b in BOX.items() if now - b.seen > 600 and u not in IN_CALL]:    # давно не заходили — ящик не нужен
        BOX.pop(u, None)


async def _reaper():
    while True:
        await asyncio.sleep(3)
        try:
            await sweep()
        except Exception:
            log.exception("calls sweep failed")


def start():
    global _task
    if _task is None or _task.done():
        _task = asyncio.ensure_future(_reaper())


def install(r, A):
    r.add_get(A + "/calls/poll", a_poll)
    r.add_get(A + "/calls/ice", a_ice)
    r.add_get(A + "/calls/active", a_active)
    r.add_post(A + "/calls/start", a_start)
    r.add_post(A + "/calls/join", a_join)
    r.add_post(A + "/calls/decline", a_decline)
    r.add_post(A + "/calls/leave", a_leave)
    r.add_post(A + "/calls/invite", a_invite)
    r.add_post(A + "/calls/sig", a_sig)
    r.add_post(A + "/calls/state", a_state)
