# -*- coding: utf-8 -*-
"""
KMBP FORUM — системные push-уведомления и звонки при ЗАКРЫТОМ приложении (Android, Firebase Cloud Messaging).

Как это работает (так же, как в Telegram / WhatsApp):
  • Приложение при входе получает у Google «FCM-токен» устройства и присылает его сюда (POST /push/register).
  • Когда звонят / пишут / комментируют, сервер отправляет на токен data-сообщение с высоким приоритетом
    (FCM HTTP v1). Google будит приложение даже если оно закрыто (смахнуто из «недавних» — исключение: «Принудительная
    остановка» в настройках), и нативная служба `ExgMessagingService` показывает:
        – звонок: полноэкранный экран входящего вызова поверх блокировки, мелодия + вибрация, «Принять» / «Отклонить»;
        – сообщение / комментарий / упоминание: обычное уведомление, по нажатию открывается нужный чат или пост.
  • Если звонок отменили / приняли на другом устройстве / истёк таймаут — приходит «call_end», вызов гаснет.

Настройка (один раз):
  1. console.firebase.google.com → создать проект → добавить Android-приложение с пакетом  com.exg.forum
     → скачать google-services.json (нужен для сборки APK, см. android-app/README.md).
  2. Project settings → Service accounts → «Generate new private key» → JSON-файл.
  3. На сервере форума задать переменную окружения (одну из):
        FCM_SERVICE_ACCOUNT        — содержимое JSON целиком (или то же, закодированное в base64 — удобно для хостингов)
        FCM_SERVICE_ACCOUNT_FILE   — путь к JSON-файлу  (или стандартная GOOGLE_APPLICATION_CREDENTIALS)
  Без этого пуши выключены, всё остальное работает как раньше (long-poll + дублирование в Telegram).

Другие переменные (необязательные):
  FCM_DISABLE=1   — принудительно выключить.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time


import forum as F
from forum import J, api, jbody

log = logging.getLogger("jins.fcm")
P = F.P

DDL = """
CREATE TABLE IF NOT EXISTS forum_push_tokens(
    token TEXT PRIMARY KEY, user_id BIGINT NOT NULL, session TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT 'android',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS forum_push_tokens_user_idx ON forum_push_tokens(user_id);
"""

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_acc = None            # сервисный аккаунт (dict) или False, если не настроен
_tok = {"v": "", "exp": 0.0}
_lock = None
_http = None
_have = {}             # uid -> (monotonic, bool): есть ли у пользователя токены (чтобы не дёргать БД на каждый чих)


# ============================================================================ доступ к Google
def _load():
    global _acc
    if _acc is not None:
        return _acc or None
    _acc = False
    if os.getenv("FCM_DISABLE", "") in ("1", "true", "yes"):
        return None
    raw = (os.getenv("FCM_SERVICE_ACCOUNT") or "").strip()
    try:
        if not raw:
            path = os.getenv("FCM_SERVICE_ACCOUNT_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
            if path and os.path.exists(path):
                raw = open(path, encoding="utf-8").read()
        if raw and not raw.lstrip().startswith("{"):
            raw = base64.b64decode(raw).decode("utf-8")
        if raw:
            d = json.loads(raw)
            if d.get("private_key") and d.get("client_email") and d.get("project_id"):
                _acc = d
                log.info("FCM: включено (проект %s)", d["project_id"])
    except Exception:
        log.exception("FCM: не удалось прочитать сервисный аккаунт")
    if not _acc:
        log.info("FCM: не настроено (задайте FCM_SERVICE_ACCOUNT) — системные пуши и звонки при закрытом приложении выключены")
    return _acc or None


def enabled():
    return _load() is not None


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt(acc):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"iss": acc["client_email"], "scope": SCOPE, "aud": "https://oauth2.googleapis.com/token",
                            "iat": now, "exp": now + 3300}).encode())
    key = serialization.load_pem_private_key(acc["private_key"].encode(), password=None)
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64(sig)}"


def session():
    global _http
    from aiohttp import ClientSession, ClientTimeout
    s = getattr(F.bm, "HTTP", None)
    if s is not None and not s.closed:
        return s
    if _http is None or _http.closed:
        _http = ClientSession(timeout=ClientTimeout(total=20))
    return _http


async def _access():
    global _lock
    acc = _load()
    if not acc:
        return ""
    if _tok["v"] and time.time() < _tok["exp"] - 120:
        return _tok["v"]
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if _tok["v"] and time.time() < _tok["exp"] - 120:
            return _tok["v"]
        assertion = await asyncio.get_running_loop().run_in_executor(None, _jwt, acc)
        async with session().post("https://oauth2.googleapis.com/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}) as r:
            d = await r.json(content_type=None)
        if not d.get("access_token"):
            raise RuntimeError("FCM oauth: %s" % str(d)[:200])
        _tok["v"], _tok["exp"] = d["access_token"], time.time() + int(d.get("expires_in") or 3300)
        return _tok["v"]


# ============================================================================ отправка
async def _send_one(token, data, ttl, collapse=""):
    acc = _load()
    msg = {"token": token, "data": {k: str(v) for k, v in data.items()},
           "android": {"priority": "HIGH", "ttl": "%ds" % ttl}}
    if collapse:
        msg["android"]["collapse_key"] = collapse
    try:
        at = await _access()
        async with session().post(f"https://fcm.googleapis.com/v1/projects/{acc['project_id']}/messages:send",
                                  json={"message": msg}, headers={"Authorization": "Bearer " + at}) as r:
            if r.status == 200:
                return True
            body = await r.text()
            if r.status == 401:
                _tok["v"] = ""
            if r.status in (400, 404) and ("UNREGISTERED" in body or "registration token" in body.lower() or "NOT_FOUND" in body):
                await P().execute("DELETE FROM forum_push_tokens WHERE token=$1", token)      # приложение удалено / токен протух
            else:
                log.warning("FCM send %s: %s", r.status, body[:200])
    except Exception as e:
        log.warning("FCM send failed: %s", e)
    return False


async def has_tokens(uid):
    now = time.monotonic()
    c = _have.get(uid)
    if c and now - c[0] < 30:
        return c[1]
    ok = bool(await P().fetchval("SELECT 1 FROM forum_push_tokens WHERE user_id=$1", uid))
    if len(_have) > 5000:
        _have.clear()
    _have[uid] = (now, ok)
    return ok


async def send(uid, data, ttl=3600, collapse=""):
    """Отправить data-сообщение на все устройства пользователя. Тихо ничего не делает, если FCM не настроен."""
    if not enabled() or not uid or not await has_tokens(uid):
        return
    rows = await P().fetch("SELECT token FROM forum_push_tokens WHERE user_id=$1", uid)
    if rows:
        await asyncio.gather(*[_send_one(r["token"], data, ttl, collapse) for r in rows], return_exceptions=True)


def spawn(coro):
    """Запустить отправку в фоне (ошибки не должны ломать основной запрос)."""
    async def run():
        try:
            await coro
        except Exception:
            log.exception("FCM task failed")
    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        coro.close()


# ---------- готовые сообщения
def call_ring(uid, c, by_user):
    """Входящий звонок. by_user — {"id","name",...} звонящего."""
    if not enabled():
        return
    spawn(send(uid, {"type": "call", "call": c["id"], "kind": c["kind"], "video": "1" if c["video"] else "0",
                     "name": (c["title"] if c["kind"] == "group" and c["title"] else (by_user or {}).get("name") or "Звонок"),
                     "by": (by_user or {}).get("name") or "", "by_id": (by_user or {}).get("id") or 0,
                     "ring": 45}, ttl=45, collapse="call"))


def call_end(uid, call_id):
    """Вызов закончился / принят на другом устройстве — погасить звонящий экран."""
    if not enabled():
        return
    spawn(send(uid, {"type": "call_end", "call": call_id}, ttl=60, collapse="call"))


def text(uid, kind, title, body, href, tag, ttl=86400):
    """Обычное уведомление (сообщение, комментарий, упоминание, подписка…)."""
    if not enabled():
        return
    spawn(send(uid, {"type": "msg", "kind": kind, "title": (title or "KMBP FORUM")[:80], "body": (body or "")[:300],
                     "href": href or "", "tag": tag or ""}, ttl=ttl))


async def dm(sender, peer, body, fname, fmime):
    """Личное сообщение (чат без звука не беспокоит; Поддержка и себе — нет)."""
    if not enabled() or not peer or peer == sender or not await has_tokens(peer):
        return
    bm = F.bm
    try:
        if await P().fetchval("SELECT 1 FROM forum_chat_prefs WHERE user_id=$1 AND peer_id=$2 AND muted", peer, sender):
            return
        who = await bm.user_name(sender)
        text(peer, "dm", who, bm.dm_preview(body or "", fname, fmime) or "Новое сообщение", f"#/c/{sender}", f"dm-{sender}")
    except Exception:
        log.exception("FCM dm failed")


async def group_msg(gid, sender, title, body, fname, fmime, sticker=False, channel=False):
    """Сообщение в группе / посты канала: всем участникам, кроме отправителя и тех, кто выключил звук чата."""
    if not enabled():
        return
    bm = F.bm
    try:
        rows = await P().fetch(
            "SELECT user_id FROM forum_group_members WHERE group_id=$1 AND user_id<>$2 AND NOT muted AND NOT archived LIMIT 600", gid, sender)
        if not rows:
            return
        who = await bm.user_name(sender)
        pv = "🎭 Стикер" if sticker else (bm.dm_preview(body or "", fname, fmime) or "Новое сообщение")
        msg = pv if channel else f"{who}: {pv}"
        for r in rows:
            text(r["user_id"], "group", title or "Чат", msg, f"#/g/{gid}", f"g-{gid}")
    except Exception:
        log.exception("FCM group msg failed")


# ============================================================================ API
def _bearer(request):
    h = request.headers.get("Authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


@api
async def a_register(request):
    me = request["fuid"]
    d = await jbody(request)
    tok = str(d.get("token") or "").strip()
    if not (20 <= len(tok) <= 4096):
        raise F.FErr(400, "bad_input", "Неверный токен")
    await P().execute(
        "INSERT INTO forum_push_tokens(token,user_id,session,platform) VALUES($1,$2,$3,'android') "
        "ON CONFLICT (token) DO UPDATE SET user_id=$2, session=$3, updated_at=now()", tok, me, _bearer(request))
    _have.pop(me, None)
    # на одного пользователя — не больше 8 устройств (самые старые удаляем)
    await P().execute("DELETE FROM forum_push_tokens WHERE user_id=$1 AND token NOT IN "
                      "(SELECT token FROM forum_push_tokens WHERE user_id=$1 ORDER BY updated_at DESC LIMIT 8)", me)
    return J({"ok": True, "enabled": enabled()})


@api
async def a_unregister(request):
    me = request["fuid"]
    d = await jbody(request)
    tok = str(d.get("token") or "").strip()
    if tok:
        await P().execute("DELETE FROM forum_push_tokens WHERE token=$1 AND user_id=$2", tok, me)
    else:
        await P().execute("DELETE FROM forum_push_tokens WHERE session=$1", _bearer(request))
    _have.pop(me, None)
    return J({"ok": True})


@api
async def a_status(request):
    return J({"enabled": enabled()})


def install(r, A):
    r.add_post(A + "/push/register", a_register)
    r.add_post(A + "/push/unregister", a_unregister)
    r.add_get(A + "/push/status", a_status)


async def start(bm):
    await bm.pool.execute(DDL)
    _load()
