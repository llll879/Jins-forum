# -*- coding: utf-8 -*-
"""
KMBP FORUM — групповые чаты, каналы (в том числе для разделов), упоминания, стикеры и эмодзи-паки.

Подключается из forum.py (install / start). Работает в той же базе и с теми же сессиями, что и остальной форум.

  • Группа — все участники пишут; канал — пишут только владелец и админы канала. И то и другое может быть
    публичным (находится в каталоге, вступить можно самому) или закрытым (только по коду или по добавлению админом).
  • Чат/канал раздела: у раздела форума (forum_boards) может быть по одной группе и одному каналу. Они всегда публичные,
    создают их главные админы, а модерируют все админы бота.
  • В группах то же, что в личных чатах: ответы, закрепы, пересылка, правка, удаление, реакции, голосовые, кружки, файлы.
  • Упоминания @username: упомянутый (и тот, кому ответили) получает уведомление и метку «@» в списке чатов.
  • Стикеры и эмодзи-паки: любой пользователь создаёт наборы (картинки), добавляет чужие публичные наборы и
    отправляет стикеры в личные чаты и группы; эмодзи из паков вставляются в текст токеном :em123:.
  • Ссылки exg/имя (forum_names.py): у публичных групп и каналов — юзернейм, у закрытых — приглашение exg/+токен,
    у наборов — имя, которое создаётся само. Вступить / добавить набор можно, вставив ссылку.
"""
from __future__ import annotations

import asyncio
import hmac
import re
import secrets
import time
from datetime import datetime, timezone

from aiohttp import web

import forum as F
import forum_names as N
from forum import FErr, J, api, ghost, jbody, to_int, users_map

P = F.P

DDL = """
CREATE TABLE IF NOT EXISTS forum_groups(
    id SERIAL PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'group', title TEXT NOT NULL, descr TEXT NOT NULL DEFAULT '',
    owner_id BIGINT NOT NULL, board_id INT REFERENCES forum_boards(id) ON DELETE SET NULL, is_public BOOLEAN NOT NULL DEFAULT FALSE,
    invite TEXT NOT NULL, avatar_data BYTEA, avatar_mime TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted BOOLEAN NOT NULL DEFAULT FALSE);
CREATE UNIQUE INDEX IF NOT EXISTS forum_groups_invite_idx ON forum_groups(invite);
CREATE UNIQUE INDEX IF NOT EXISTS forum_groups_board_idx ON forum_groups(board_id, kind) WHERE board_id IS NOT NULL AND NOT deleted;
CREATE TABLE IF NOT EXISTS forum_group_members(
    group_id INT NOT NULL REFERENCES forum_groups(id) ON DELETE CASCADE, user_id BIGINT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_read BIGINT NOT NULL DEFAULT 0, muted BOOLEAN NOT NULL DEFAULT FALSE,
    pinned_at TIMESTAMPTZ, archived BOOLEAN NOT NULL DEFAULT FALSE, PRIMARY KEY(group_id, user_id));
CREATE INDEX IF NOT EXISTS forum_group_members_user_idx ON forum_group_members(user_id);
CREATE TABLE IF NOT EXISTS forum_group_msgs(
    id BIGSERIAL PRIMARY KEY, group_id INT NOT NULL REFERENCES forum_groups(id) ON DELETE CASCADE, sender_id BIGINT NOT NULL,
    body TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), edited_at TIMESTAMPTZ, pinned_at TIMESTAMPTZ,
    reply_to BIGINT, fwd_from BIGINT, file_data BYTEA, file_mime TEXT, file_name TEXT, file_size INT,
    voice_dur INT, voice_wave TEXT, sticker_id INT);
CREATE INDEX IF NOT EXISTS forum_group_msgs_idx ON forum_group_msgs(group_id, id DESC);
CREATE TABLE IF NOT EXISTS forum_group_hidden(user_id BIGINT NOT NULL, msg_id BIGINT NOT NULL REFERENCES forum_group_msgs(id) ON DELETE CASCADE, PRIMARY KEY(user_id, msg_id));
CREATE TABLE IF NOT EXISTS forum_group_heard(msg_id BIGINT NOT NULL REFERENCES forum_group_msgs(id) ON DELETE CASCADE, user_id BIGINT NOT NULL, PRIMARY KEY(msg_id, user_id));
CREATE TABLE IF NOT EXISTS forum_group_rx(
    msg_id BIGINT NOT NULL REFERENCES forum_group_msgs(id) ON DELETE CASCADE, user_id BIGINT NOT NULL, emoji TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(msg_id, user_id));
CREATE TABLE IF NOT EXISTS forum_group_mentions(
    msg_id BIGINT NOT NULL REFERENCES forum_group_msgs(id) ON DELETE CASCADE, user_id BIGINT NOT NULL, group_id INT NOT NULL, PRIMARY KEY(msg_id, user_id));
CREATE INDEX IF NOT EXISTS forum_group_mentions_idx ON forum_group_mentions(user_id, group_id);
ALTER TABLE forum_notifs ADD COLUMN IF NOT EXISTS group_id INT;
ALTER TABLE forum_notifs ADD COLUMN IF NOT EXISTS msg_id BIGINT;
CREATE TABLE IF NOT EXISTS forum_stickerpacks(
    id SERIAL PRIMARY KEY, owner_id BIGINT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'sticker', is_public BOOLEAN NOT NULL DEFAULT TRUE,
    code TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), deleted BOOLEAN NOT NULL DEFAULT FALSE);
CREATE UNIQUE INDEX IF NOT EXISTS forum_stickerpacks_code_idx ON forum_stickerpacks(code);
CREATE TABLE IF NOT EXISTS forum_stickers(
    id SERIAL PRIMARY KEY, pack_id INT NOT NULL REFERENCES forum_stickerpacks(id) ON DELETE CASCADE, data BYTEA NOT NULL, mime TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '', pos INT NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS forum_stickers_pack_idx ON forum_stickers(pack_id, pos, id);
CREATE TABLE IF NOT EXISTS forum_user_packs(
    user_id BIGINT NOT NULL, pack_id INT NOT NULL REFERENCES forum_stickerpacks(id) ON DELETE CASCADE, added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, pack_id));
CREATE TABLE IF NOT EXISTS forum_msg_stickers(msg_id BIGINT PRIMARY KEY REFERENCES direct_messages(id) ON DELETE CASCADE, sticker_id INT NOT NULL);
"""

TITLE_MAX, DESCR_MAX, TEXT_MAX = 60, 300, 3000
MAX_MEMBERS, MAX_OWNED, MAX_JOINED = 2000, 20, 200
MAX_PINNED_CHATS = 5
MAX_PINS = 20
STK_MAX, EMO_MAX = 512 * 1024, 160 * 1024            # размер одной картинки стикера / эмодзи
STK_ANIM_MAX, EMO_ANIM_MAX = 1024 * 1024, 256 * 1024  # то же для анимации (WebM, анимированный WebP / APNG / GIF)
STK_PER_PACK, EMO_PER_PACK = 60, 120
PACKS_OWNED, PACKS_ADDED = 20, 100
EM_RE = re.compile(r":em(\d{1,9}):")
MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{4,32})")
_gtyping = {}      # (группа, пользователь) -> (monotonic, 'typ'|'rec'|'vid')


def bm():
    return F.bm


# ============================================================================ доступ
GSQL = ("SELECT id,kind,title,descr,owner_id,board_id,is_public,invite,created_at,(avatar_data IS NOT NULL) av FROM forum_groups")


class Ctx:
    """Группа + кто я в ней. admin — владелец/админ группы или админ бота в чате раздела."""
    def __init__(self, g, m, staff):
        self.g, self.m = g, m
        self.role = m["role"] if m else None
        self.member = bool(m)
        self.admin = self.role in ("owner", "admin") or bool(staff and g["board_id"])
        self.owner = self.role == "owner"
        self.channel = g["kind"] == "channel"
        self.see = self.member or bool(g["is_public"]) or bool(staff and g["board_id"])
        self.can_post = self.member and (not self.channel or self.role in ("owner", "admin"))


async def ctx(me, gid, need="see"):
    g = await P().fetchrow(GSQL + " WHERE id=$1 AND NOT deleted", gid)
    if not g:
        raise FErr(404, "not_found", "Чат не найден или удалён")
    m = await P().fetchrow("SELECT role,last_read,muted,pinned_at,archived FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, me)
    staff = bool(g["board_id"]) and not m and await F.is_staff(me)
    c = Ctx(g, m, staff)
    if need == "see" and not c.see:
        raise FErr(403, "forbidden", "Этот чат закрытый")
    if need == "member" and not c.member:
        raise FErr(403, "not_member", "Вы не участник этого чата")
    if need == "post" and not c.can_post:
        raise FErr(403, "forbidden", "В канале пишут только админы" if c.channel and c.member else "Вы не участник этого чата")
    if need == "admin" and not c.admin:
        raise FErr(403, "forbidden", "Нужны права админа")
    if need == "owner" and not (c.owner or (staff and await bm().is_main(me))):
        raise FErr(403, "forbidden", "Это может только владелец")
    return c


def short_user(u):
    return {"id": u["id"], "name": u["name"], "username": u["username"], "av": u["av"], "sb": u["sb"]}


def strip_em(s):
    return EM_RE.sub("🙂", s or "")


def check_text(text):
    if len(EM_RE.findall(text)) > 40:
        raise FErr(400, "too_many_emoji", "Не больше 40 эмодзи из паков в одном сообщении")


def file_sig(mid):
    return bm().img_url("gm", mid).split("t=")[1]


def file_url(mid):
    return "/forum/api/groups/file/%d?t=%s" % (mid, file_sig(mid))


def preview(r, with_name=None):
    """Подпись сообщения в списке чатов (r — строка с body, file_*, voice_dur, sticker_id)."""
    if r["sticker_id"]:
        t = "🖼 Стикер"
    elif r["body"]:
        t = strip_em(r["body"])
    elif r["voice_dur"]:
        t = "📹 Видеосообщение" if bm().note_mime(r["file_mime"]) else "🎤 Голосовое сообщение"
    elif r["file_name"] or r["file_mime"]:
        k, _ = F.attach_info(r["file_name"] or "", r["file_mime"])
        t = ("GIF" if r["file_mime"] == "image/gif" else "📷 Фото") if k == "image" else "🎬 Видео" if k == "video" else "📎 " + (r["file_name"] or "Файл")
    else:
        t = ""
    return ((with_name + ": ") if with_name and t else "") + t


# ============================================================================ список чатов
async def my_groups(me):
    rows = await P().fetch(
        """SELECT g.id,g.kind,g.title,g.board_id,(g.avatar_data IS NOT NULL) av,g.created_at,gm.role,gm.muted,gm.pinned_at,gm.archived,
             lm.sender_id lsender,lm.body,lm.created_at lts,lm.file_name,lm.file_mime,lm.voice_dur,lm.sticker_id,
             (SELECT count(*) FROM forum_group_msgs m WHERE m.group_id=g.id AND m.id>gm.last_read AND m.sender_id<>$1
                AND NOT EXISTS(SELECT 1 FROM forum_group_hidden h WHERE h.user_id=$1 AND h.msg_id=m.id))::int unread,
             (SELECT count(*) FROM forum_group_mentions mm WHERE mm.group_id=g.id AND mm.user_id=$1)::int ments
           FROM forum_group_members gm JOIN forum_groups g ON g.id=gm.group_id AND NOT g.deleted
           LEFT JOIN LATERAL (SELECT sender_id,body,created_at,file_name,file_mime,voice_dur,sticker_id FROM forum_group_msgs m WHERE m.group_id=g.id
                AND NOT EXISTS(SELECT 1 FROM forum_group_hidden h WHERE h.user_id=$1 AND h.msg_id=m.id) ORDER BY m.id DESC LIMIT 1) lm ON TRUE
           WHERE gm.user_id=$1 LIMIT 200""", me)
    um = await users_map([r["lsender"] for r in rows if r["lsender"]])
    out = []
    for r in rows:
        n = r["unread"]
        muted = bool(r["muted"])
        arch = bool(r["archived"]) and not (n and not muted)
        who = None
        if r["lsender"] and r["kind"] == "group":
            who = "Вы" if r["lsender"] == me else (um.get(r["lsender"]) or ghost(r["lsender"]))["name"].split(" ")[0]
        out.append({"id": r["id"], "kind": r["kind"], "title": r["title"], "av": bool(r["av"]), "board": r["board_id"],
                    "last": preview(r, who)[:120], "ts": (r["lts"] or r["created_at"]).timestamp(), "mine": r["lsender"] == me,
                    "unread": n, "ments": r["ments"], "pin": r["pinned_at"].timestamp() if r["pinned_at"] else 0,
                    "muted": muted, "arch": arch, "role": r["role"]})
    return out


async def search_msgs(me, q, like):
    rows = await P().fetch(
        """SELECT m.id,m.group_id,m.sender_id,m.body,m.created_at,g.title,g.kind,(g.avatar_data IS NOT NULL) av
           FROM forum_group_msgs m JOIN forum_group_members gm ON gm.group_id=m.group_id AND gm.user_id=$1
           JOIN forum_groups g ON g.id=m.group_id AND NOT g.deleted
           WHERE m.body ILIKE $2 AND NOT EXISTS(SELECT 1 FROM forum_group_hidden h WHERE h.user_id=$1 AND h.msg_id=m.id)
           ORDER BY m.id DESC LIMIT 30""", me, like)
    um = await users_map([r["sender_id"] for r in rows])
    out, ql = [], q.lower()
    for r in rows:
        body = " ".join(strip_em(r["body"]).split())
        i = max(body.lower().find(ql), 0)
        st = max(0, i - 35)
        out.append({"id": r["id"], "g": {"id": r["group_id"], "title": r["title"], "kind": r["kind"], "av": bool(r["av"])},
                    "user": um.get(r["sender_id"]) or ghost(r["sender_id"]), "mine": r["sender_id"] == me,
                    "ts": r["created_at"].timestamp(), "text": ("…" if st else "") + body[st:st + 140]})
    return out


async def unread_summary(me):
    """Для ping: сколько непрочитанного в группах без «звука» и какой чат показать в баннере."""
    n = await P().fetchval(
        """SELECT COALESCE(sum((SELECT count(*) FROM forum_group_msgs m WHERE m.group_id=gm.group_id AND m.id>gm.last_read AND m.sender_id<>$1
             AND NOT EXISTS(SELECT 1 FROM forum_group_hidden h WHERE h.user_id=$1 AND h.msg_id=m.id))),0)::int
           FROM forum_group_members gm JOIN forum_groups g ON g.id=gm.group_id AND NOT g.deleted WHERE gm.user_id=$1 AND NOT gm.muted""", me)
    top = None
    if n:
        top = await P().fetchrow(
            """SELECT g.id,g.title FROM forum_group_members gm JOIN forum_groups g ON g.id=gm.group_id AND NOT g.deleted
               WHERE gm.user_id=$1 AND NOT gm.muted AND EXISTS(SELECT 1 FROM forum_group_msgs m WHERE m.group_id=gm.group_id AND m.id>gm.last_read AND m.sender_id<>$1)
               ORDER BY (SELECT max(id) FROM forum_group_msgs m WHERE m.group_id=gm.group_id) DESC LIMIT 1""", me)
    return n or 0, ({"id": top["id"], "name": top["title"], "g": True} if top else None)


# ============================================================================ создание, каталог, вступление
async def _can_dm(me, uid):
    by_me, by_peer = await bm().block_state(me, uid)
    return not (by_me or by_peer)


def _item(r, mine_ids=(), names=None):
    return {"id": r["id"], "kind": r["kind"], "title": r["title"], "descr": (r["descr"] or "")[:160], "av": bool(r["av"]),
            "members": r["n"], "member": r["id"] in mine_ids, "board": r["board_id"], "username": (names or {}).get(r["id"])}


async def _items(rows, mine_ids=()):
    names = await N.get_many("group", [r["id"] for r in rows])
    return [_item(r, mine_ids, names) for r in rows]


@api
async def a_gcreate(request):
    me = request["fuid"]
    d = await jbody(request)
    kind = "channel" if d.get("kind") == "channel" else "group"
    title = str(d.get("title") or "").strip()[:TITLE_MAX]
    descr = str(d.get("descr") or "").strip()[:DESCR_MAX]
    if not title:
        raise FErr(400, "empty", "Введите название")
    board = to_int(d.get("board_id")) or None
    public = bool(d.get("public"))
    if board:
        if not await bm().is_main(me):
            raise FErr(403, "forbidden", "Чаты и каналы разделов создают главные админы")
        if not await P().fetchval("SELECT 1 FROM forum_boards WHERE id=$1", board):
            raise FErr(404, "not_found", "Раздел не найден")
        if await P().fetchval("SELECT 1 FROM forum_groups WHERE board_id=$1 AND kind=$2 AND NOT deleted", board, kind):
            raise FErr(409, "exists", "У раздела уже есть %s" % ("канал" if kind == "channel" else "чат"))
        public = True
    uname = str(d.get("username") or "").strip()
    if uname:
        if not public:
            raise FErr(400, "private_name", "Ссылка-имя бывает только у публичных чатов и каналов")
        uname = await N.check(uname, "group", 0)
    if not bm().rate_ok(("fgcreate", me), 15):
        raise FErr(429, "too_fast", "Не так быстро")
    if await P().fetchval("SELECT count(*) FROM forum_groups WHERE owner_id=$1 AND NOT deleted", me) >= MAX_OWNED:
        raise FErr(400, "limit", "Можно владеть не больше %d чатов и каналов" % MAX_OWNED)
    gid = await P().fetchval(
        "INSERT INTO forum_groups(kind,title,descr,owner_id,board_id,is_public,invite) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id",
        kind, title, descr, me, board, public, secrets.token_hex(5))
    await P().execute("INSERT INTO forum_group_members(group_id,user_id,role) VALUES($1,$2,'owner')", gid, me)
    if uname:
        try:
            await N.put("group", gid, uname)
        except FErr:                                   # имя успели занять между проверкой и созданием
            await P().execute("DELETE FROM forum_groups WHERE id=$1", gid)
            raise
    mem = d.get("members") if isinstance(d.get("members"), list) else []
    ids = [i for i in {to_int(x) for x in mem[:100] if isinstance(x, (int, str))} if i and i != me]
    for uid in ids:
        if await P().fetchval("SELECT 1 FROM users WHERE user_id=$1", uid) and await _can_dm(me, uid):
            await P().execute("INSERT INTO forum_group_members(group_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING", gid, uid)
    return J({"ok": True, "id": gid})


@api
async def a_gfind(request):
    """Каталог публичных чатов и каналов (q — поиск по названию и описанию) или поиск по коду приглашения (code)."""
    me = request["fuid"]
    code = (request.query.get("code") or "").strip().lower()[:20]
    q = (request.query.get("q") or "").strip()[:60]
    base = ("SELECT g.id,g.kind,g.title,g.descr,g.board_id,(g.avatar_data IS NOT NULL) av,"
            "(SELECT count(*) FROM forum_group_members x WHERE x.group_id=g.id)::int n FROM forum_groups g WHERE NOT g.deleted AND ")
    if code:
        rows = await P().fetch(base + "g.invite=$1", code)
    elif q:
        rows = await P().fetch(
            base + "g.is_public AND (g.title ILIKE $1 OR g.descr ILIKE $1 OR g.id IN (SELECT ref FROM forum_names WHERE kind='group' AND name ILIKE $1)) "
                   "ORDER BY n DESC LIMIT 40", F._like(q.lstrip("@")))
    else:
        rows = await P().fetch(base + "g.is_public ORDER BY n DESC, g.id DESC LIMIT 40")
    mine = {r["group_id"] for r in await P().fetch("SELECT group_id FROM forum_group_members WHERE user_id=$1", me)}
    return J({"items": await _items(rows, mine)})


@api
async def a_gboard(request):
    """Чат и канал раздела форума."""
    me = request["fuid"]
    bid = to_int(request.query.get("id"))
    rows = await P().fetch(
        "SELECT g.id,g.kind,g.title,g.descr,g.board_id,(g.avatar_data IS NOT NULL) av,(SELECT count(*) FROM forum_group_members x WHERE x.group_id=g.id)::int n "
        "FROM forum_groups g WHERE g.board_id=$1 AND NOT g.deleted ORDER BY g.kind", bid)
    mine = {r["group_id"] for r in await P().fetch("SELECT group_id FROM forum_group_members WHERE user_id=$1", me)}
    return J({"items": await _items(rows, mine)})


@api
async def a_gjoin(request):
    me = request["fuid"]
    d = await jbody(request)
    code = str(d.get("code") or "").strip().lower()[:20]
    gid = to_int(d.get("id"))
    if code:
        gid = await P().fetchval("SELECT id FROM forum_groups WHERE invite=$1 AND NOT deleted", code) or 0
        if not gid:
            raise FErr(404, "not_found", "Код не найден")
    c = await ctx(me, gid, "see" if not code else None)
    if c.member:
        return J({"ok": True, "id": gid})
    if not code and not c.g["is_public"]:
        raise FErr(403, "forbidden", "Этот чат закрытый — нужен код приглашения")
    if await P().fetchval("SELECT count(*) FROM forum_group_members WHERE group_id=$1", gid) >= MAX_MEMBERS:
        raise FErr(400, "full", "В чате уже максимум участников")
    if await P().fetchval("SELECT count(*) FROM forum_group_members WHERE user_id=$1", me) >= MAX_JOINED:
        raise FErr(400, "limit", "Вы состоите в слишком многих чатах")
    await P().execute(
        "INSERT INTO forum_group_members(group_id,user_id,last_read) VALUES($1,$2,COALESCE((SELECT max(id) FROM forum_group_msgs WHERE group_id=$1),0)) ON CONFLICT DO NOTHING", gid, me)
    return J({"ok": True, "id": gid})


@api
async def a_gleave(request):
    me = request["fuid"]
    gid = to_int((await jbody(request)).get("id"))
    c = await ctx(me, gid, "member")
    await P().execute("DELETE FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, me)
    if c.owner:      # владелец ушёл: передаём права старейшему админу, потом старейшему участнику; если никого — чат удаляется
        nxt = await P().fetchval(
            "SELECT user_id FROM forum_group_members WHERE group_id=$1 ORDER BY (role='admin') DESC, joined_at LIMIT 1", gid)
        if nxt:
            await P().execute("UPDATE forum_group_members SET role='owner' WHERE group_id=$1 AND user_id=$2", gid, nxt)
            await P().execute("UPDATE forum_groups SET owner_id=$2 WHERE id=$1", gid, nxt)
        else:
            await P().execute("DELETE FROM forum_groups WHERE id=$1", gid)
            await N.drop("group", gid)
    return J({"ok": True})


@api
async def a_gdelete(request):
    me = request["fuid"]
    gid = to_int((await jbody(request)).get("id"))
    await ctx(me, gid, "owner")
    await P().execute("DELETE FROM forum_groups WHERE id=$1", gid)
    await N.drop("group", gid)
    return J({"ok": True})


# ============================================================================ информация, участники, права
@api
async def a_ginfo(request):
    me = request["fuid"]
    gid = to_int(request.query.get("id"))
    c = await ctx(me, gid, "see")
    g = c.g
    n = await P().fetchval("SELECT count(*) FROM forum_group_members WHERE group_id=$1", gid)
    board = None
    if g["board_id"]:
        board = await P().fetchval("SELECT name FROM forum_boards WHERE id=$1", g["board_id"])
    return J({"id": gid, "kind": g["kind"], "title": g["title"], "descr": g["descr"], "public": bool(g["is_public"]), "av": bool(g["av"]),
              "members": n, "member": c.member, "role": c.role, "admin": c.admin, "owner": c.owner,
              "can_post": c.can_post, "board": g["board_id"], "board_name": board, "invite": g["invite"] if c.admin else None,
              "username": await N.get("group", gid),
              "muted": bool(c.m and c.m["muted"]), "created": g["created_at"].timestamp()})


@api
async def a_gmembers(request):
    me = request["fuid"]
    gid = to_int(request.query.get("id"))
    c = await ctx(me, gid, "see")
    q = (request.query.get("q") or "").strip()[:40].lstrip("@")
    off = max(to_int(request.query.get("off")), 0)
    args = [gid, off]
    where = ""
    if q:
        where = " AND (u.username ILIKE $3 OR fn.name ILIKE $3 OR u.first_name ILIKE $3 OR u.last_name ILIKE $3)"
        args.append(F._like(q))
    rows = await P().fetch(
        "SELECT gm.user_id,gm.role FROM forum_group_members gm JOIN users u ON u.user_id=gm.user_id "
        "LEFT JOIN forum_names fn ON fn.kind='user' AND fn.ref=gm.user_id WHERE gm.group_id=$1" + where +
        " ORDER BY (gm.role='owner') DESC,(gm.role='admin') DESC,gm.joined_at OFFSET $2 LIMIT 100", *args)
    um = await users_map([r["user_id"] for r in rows])
    return J({"members": [{"user": um.get(r["user_id"]) or ghost(r["user_id"]), "role": r["role"]} for r in rows],
              "more": len(rows) == 100, "me": c.role})


@api
async def a_gmention(request):
    """Подсказка при вводе @ в группе: участники, подходящие под строку."""
    me = request["fuid"]
    gid = to_int(request.query.get("id"))
    await ctx(me, gid, "see")
    q = (request.query.get("q") or "").strip()[:32].lstrip("@")
    like = F._like(q) if q else "%"
    rows = await P().fetch(
        """SELECT gm.user_id FROM forum_group_members gm JOIN users u ON u.user_id=gm.user_id
           LEFT JOIN forum_names fn ON fn.kind='user' AND fn.ref=gm.user_id
           WHERE gm.group_id=$1 AND gm.user_id<>$2 AND COALESCE(fn.name,u.username,'')<>''
           AND (u.username ILIKE $3 OR fn.name ILIKE $3 OR u.first_name ILIKE $3 OR u.last_name ILIKE $3)
           ORDER BY u.last_seen DESC NULLS LAST LIMIT 8""", gid, me, like)
    um = await users_map([r["user_id"] for r in rows])
    return J({"users": [short_user(um[r["user_id"]]) for r in rows if r["user_id"] in um]})


@api
async def a_gupdate(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("id"))
    c = await ctx(me, gid, "admin")
    title = str(d.get("title", c.g["title"]) or "").strip()[:TITLE_MAX]
    if not title:
        raise FErr(400, "empty", "Введите название")
    descr = str(d.get("descr", c.g["descr"]) or "").strip()[:DESCR_MAX]
    public = bool(d["public"]) if "public" in d and not c.g["board_id"] else bool(c.g["is_public"])
    uname = None                                  # None — не трогаем, "" — снять, иначе новое имя
    if "username" in d:
        uname = str(d.get("username") or "").strip()
        if uname:
            if not public:
                raise FErr(400, "private_name", "Ссылка-имя бывает только у публичных чатов и каналов")
            uname = await N.check(uname, "group", gid)
    await P().execute("UPDATE forum_groups SET title=$2,descr=$3,is_public=$4 WHERE id=$1", gid, title, descr, public)
    if uname is not None or not public:
        await N.put("group", gid, uname if public else "")
    if d.get("reset_invite"):
        await P().execute("UPDATE forum_groups SET invite=$2 WHERE id=$1", gid, secrets.token_hex(5))
    return J({"ok": True})


@api
async def a_gavatar_set(request):
    me = request["fuid"]
    form = await request.post()
    gid = to_int(form.get("id"))
    await ctx(me, gid, "admin")
    if form.get("remove"):
        await P().execute("UPDATE forum_groups SET avatar_data=NULL,avatar_mime=NULL WHERE id=$1", gid)
        return J({"ok": True})
    f = form.get("file")
    if f is None or not hasattr(f, "file"):
        raise FErr(400, "no_file", "Файл не выбран")
    data = f.file.read()
    mime = _img_mime(data)
    if not data or len(data) > F.IMG_MAX or not mime:
        raise FErr(400, "bad_image", "Нужна картинка до 4 МБ (JPEG, PNG, WebP)")
    await P().execute("UPDATE forum_groups SET avatar_data=$2,avatar_mime=$3 WHERE id=$1", gid, data, mime)
    return J({"ok": True})


async def a_gavatar(request):
    r = await P().fetchrow("SELECT avatar_data,avatar_mime FROM forum_groups WHERE id=$1 AND NOT deleted", to_int(request.match_info.get("gid")))
    if not r or not r["avatar_data"]:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(r["avatar_data"]), content_type=r["avatar_mime"] or "image/jpeg",
                        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"})


@api
async def a_gadd(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("id"))
    c = await ctx(me, gid, "admin")
    mem = d.get("user_ids") if isinstance(d.get("user_ids"), list) else []
    ids = [i for i in {to_int(x) for x in mem[:50] if isinstance(x, (int, str))} if i and i != me]
    have = await P().fetchval("SELECT count(*) FROM forum_group_members WHERE group_id=$1", gid)
    added = 0
    for uid in ids:
        if have + added >= MAX_MEMBERS:
            break
        if not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1 AND user_id>0", uid) or not await _can_dm(me, uid):
            continue
        r = await P().execute(
            "INSERT INTO forum_group_members(group_id,user_id,last_read) VALUES($1,$2,COALESCE((SELECT max(id) FROM forum_group_msgs WHERE group_id=$1),0)) ON CONFLICT DO NOTHING", gid, uid)
        if str(r).endswith("1"):
            added += 1
    return J({"ok": True, "added": added})


@api
async def a_gkick(request):
    me = request["fuid"]
    d = await jbody(request)
    gid, uid = to_int(d.get("id")), to_int(d.get("user_id"))
    c = await ctx(me, gid, "admin")
    t = await P().fetchval("SELECT role FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, uid)
    if not t or t == "owner" or uid == me:
        raise FErr(400, "bad_user", "Этого участника удалить нельзя")
    if t == "admin" and not (c.owner or c.role is None):
        raise FErr(403, "forbidden", "Админов удаляет только владелец")
    await P().execute("DELETE FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, uid)
    return J({"ok": True})


@api
async def a_grole(request):
    me = request["fuid"]
    d = await jbody(request)
    gid, uid = to_int(d.get("id")), to_int(d.get("user_id"))
    await ctx(me, gid, "owner")
    role = "admin" if d.get("role") == "admin" else "member"
    r = await P().execute("UPDATE forum_group_members SET role=$3 WHERE group_id=$1 AND user_id=$2 AND role<>'owner'", gid, uid, role)
    if not str(r).endswith("1"):
        raise FErr(400, "bad_user", "Роль этого участника изменить нельзя")
    return J({"ok": True, "role": role})


@api
async def a_gpref(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("id"))
    c = await ctx(me, gid, "member")
    m = c.m
    pinned_at, muted, archived = m["pinned_at"], bool(m["muted"]), bool(m["archived"])
    if "muted" in d:
        muted = bool(d["muted"])
    if "archived" in d:
        archived = bool(d["archived"])
        if archived:
            pinned_at = None
    if "pinned" in d:
        if d["pinned"]:
            if pinned_at is None:
                n = await P().fetchval("SELECT count(*) FROM forum_chat_prefs WHERE user_id=$1 AND pinned_at IS NOT NULL", me) + \
                    await P().fetchval("SELECT count(*) FROM forum_group_members WHERE user_id=$1 AND pinned_at IS NOT NULL", me)
                if n >= MAX_PINNED_CHATS:
                    raise FErr(400, "too_many_pins", "Можно закрепить не больше %d чатов" % MAX_PINNED_CHATS)
                pinned_at = datetime.now(timezone.utc)
            archived = False
        else:
            pinned_at = None
    await P().execute("UPDATE forum_group_members SET pinned_at=$3,muted=$4,archived=$5 WHERE group_id=$1 AND user_id=$2", gid, me, pinned_at, muted, archived)
    return J({"ok": True, "pin": pinned_at.timestamp() if pinned_at else 0, "muted": muted, "arch": archived})


# ============================================================================ сообщения
MSG_COLS = ("m.id,m.sender_id,m.body,m.created_at,m.edited_at,m.pinned_at,m.reply_to,m.fwd_from,m.file_name,m.file_mime,m.file_size,"
            "m.voice_dur,m.voice_wave,m.sticker_id,(m.file_data IS NOT NULL) has_file")
NOT_HIDDEN = "NOT EXISTS(SELECT 1 FROM forum_group_hidden h WHERE h.user_id=$1 AND h.msg_id=m.id)"


@api
async def a_gmessages(request):
    me = request["fuid"]
    gid = to_int(request.query.get("id"))
    c = await ctx(me, gid, "see")
    lim = min(max(to_int(request.query.get("limit"), 120), 20), 1000)
    rows = await P().fetch(
        f"SELECT * FROM (SELECT {MSG_COLS} FROM forum_group_msgs m WHERE m.group_id=$2 AND {NOT_HIDDEN} ORDER BY m.id DESC LIMIT $3) q ORDER BY id", me, gid, lim)
    if c.member and rows:
        await P().execute("UPDATE forum_group_members SET last_read=GREATEST(last_read,$3) WHERE group_id=$1 AND user_id=$2", gid, me, rows[-1]["id"])
        await P().execute("DELETE FROM forum_group_mentions WHERE group_id=$1 AND user_id=$2", gid, me)
    ids = [r["id"] for r in rows]
    # ответы: оригиналы могут быть за пределами окна
    rids = list({r["reply_to"] for r in rows if r["reply_to"]})
    replies = {}
    if rids:
        for q in await P().fetch(
                f"SELECT {MSG_COLS} FROM forum_group_msgs m WHERE m.id=ANY($2::bigint[]) AND m.group_id=$3 AND {NOT_HIDDEN}", me, rids, gid):
            replies[q["id"]] = q
    fwd_ids = {r["fwd_from"] for r in rows if r["fwd_from"]}
    uids = {r["sender_id"] for r in rows} | {q["sender_id"] for q in replies.values()} | fwd_ids
    um = await users_map(uids)
    nm = lambda u: (um.get(u) or ghost(u))["name"]
    pins = [{"id": q["id"], "text": preview(q)[:120] or "Сообщение"} for q in await P().fetch(
        f"SELECT {MSG_COLS} FROM forum_group_msgs m WHERE m.group_id=$2 AND m.pinned_at IS NOT NULL AND {NOT_HIDDEN} ORDER BY m.pinned_at DESC LIMIT {MAX_PINS}", me, gid)]
    rx, heard = {}, set()
    if ids:
        for q in await P().fetch(
                "SELECT msg_id,emoji,count(*) n,bool_or(user_id=$2) mine FROM forum_group_rx WHERE msg_id=ANY($1::bigint[]) GROUP BY msg_id,emoji ORDER BY min(created_at)", ids, me):
            rx.setdefault(q["msg_id"], []).append({"e": q["emoji"], "n": q["n"], "mine": q["mine"]})
        heard = {q["msg_id"] for q in await P().fetch("SELECT msg_id FROM forum_group_heard WHERE user_id=$2 AND msg_id=ANY($1::bigint[])", ids, me)}
    other_read = await P().fetchval("SELECT COALESCE(max(last_read),0) FROM forum_group_members WHERE group_id=$1 AND user_id<>$2", gid, me)
    now = time.monotonic()
    typing, rec = [], None
    for (g, u), (ts, k) in list(_gtyping.items()):
        if g == gid and u != me and now - ts < 5:
            if k == "typ":
                typing.append(u)
            else:
                rec = rec or ("video" if k == "vid" else "voice")
    tum = await users_map(typing[:3]) if typing else {}
    n = await P().fetchval("SELECT count(*) FROM forum_group_members WHERE group_id=$1", gid)

    def one(r):
        mine = r["sender_id"] == me
        m = {"id": r["id"], "uid": r["sender_id"], "mine": mine, "body": r["body"] or "", "ts": r["created_at"].timestamp(),
             "read": mine and r["id"] <= other_read}
        voice = note = att = None
        if r["voice_dur"] and r["has_file"]:
            if bm().note_mime(r["file_mime"]):
                note = {"url": file_url(r["id"]), "dur": r["voice_dur"], "heard": mine or r["id"] in heard}
            else:
                voice = {"url": file_url(r["id"]), "dur": r["voice_dur"], "wave": r["voice_wave"] or "", "heard": mine or r["id"] in heard}
        elif r["has_file"]:
            kind, _ = F.attach_info(r["file_name"] or "", r["file_mime"])
            att = {"url": file_url(r["id"]), "name": r["file_name"] or "Файл", "size": r["file_size"] or 0, "kind": kind}
            if r["file_mime"] == "image/gif":
                att["gif"] = True
        if rx.get(r["id"]):
            m["rx"] = rx[r["id"]]
        if r["edited_at"] is not None:
            m["edited"] = True
        if r["pinned_at"] is not None:
            m["pinned"] = True
        if r["reply_to"]:
            q = replies.get(r["reply_to"])
            m["reply"] = ({"id": q["id"], "mine": q["sender_id"] == me, "name": nm(q["sender_id"]), "text": preview(q)[:120]} if q
                          else {"id": r["reply_to"], "text": "Сообщение удалено", "gone": True})
        if r["fwd_from"]:
            m["fwd"] = nm(r["fwd_from"])
        if r["sticker_id"]:
            m["sticker"] = {"id": r["sticker_id"]}
        if att:
            m["file"] = att
        if voice:
            m["voice"] = voice
        if note:
            m["note"] = note
        return m

    g = c.g
    return J({"group": {"id": gid, "kind": g["kind"], "title": g["title"], "descr": g["descr"], "av": bool(g["av"]), "members": n,
                        "member": c.member, "admin": c.admin, "can_post": c.can_post, "public": bool(g["is_public"]), "board": g["board_id"],
                        "muted": bool(c.m and c.m["muted"])},
              "users": {u: short_user(um[u]) for u in um}, "pins": pins, "typing": [tum[u]["name"].split(" ")[0] for u in typing[:3] if u in tum],
              "recording": rec, "messages": [one(r) for r in rows]})


async def _mention_targets(gid, me, text, reply_author):
    names = list({m.lower() for m in MENTION_RE.findall(text or "")})[:20]
    got = {}
    if names:
        for r in await P().fetch(
                """SELECT gm.user_id FROM forum_group_members gm WHERE gm.group_id=$1 AND (
                     EXISTS(SELECT 1 FROM users u WHERE u.user_id=gm.user_id AND lower(u.username)=ANY($2::text[]))
                     OR EXISTS(SELECT 1 FROM forum_names n WHERE n.kind='user' AND n.ref=gm.user_id AND n.name=ANY($2::text[])))""", gid, names):
            if r["user_id"] != me:
                got[r["user_id"]] = "gmention"
    if reply_author and reply_author != me and reply_author not in got:
        if await P().fetchval("SELECT 1 FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, reply_author):
            got[reply_author] = "greply"
    return got


async def _safe(coro):
    try:
        await coro
    except Exception:
        F.log.exception("group mention notify failed")


async def _notify_mentions(gid, me, mid, text, reply_author):
    for uid, kind in (await _mention_targets(gid, me, text, reply_author)).items():
        await P().execute("INSERT INTO forum_group_mentions(msg_id,user_id,group_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", mid, uid, gid)
        await F.notify(uid, kind, me, group_id=gid, msg_id=mid)


@api
async def a_gsend(request):
    me = request["fuid"]
    fdata = fmime = fname = None
    B = bm()
    if (request.content_type or "").startswith("multipart/"):
        form = await request.post()
        d = {k: form.get(k) for k in ("id", "text", "reply_to", "voice_dur", "voice_wave", "note_dur", "sticker_id", "gif")}
        f = form.get("file")
        if f is not None and hasattr(f, "file"):
            import os
            fdata = f.file.read() or None
            fmime = str(getattr(f, "content_type", "") or "")[:100]
            fname = (os.path.basename(str(getattr(f, "filename", "") or "")) or "file")[:120]
            is_rec = bool(d.get("voice_dur") or d.get("note_dur"))
            if fdata and len(fdata) > (B.MAX_FILE if is_rec else F.ATTACH_MAX):
                raise FErr(400, "bad_size", "Запись слишком большая" if is_rec else "Файл слишком большой (до %d МБ)" % (F.ATTACH_MAX // 1048576))
    else:
        d = await jbody(request)
    gid = to_int(d.get("id"))
    c = await ctx(me, gid, "post")
    text = str(d.get("text") or "").strip()[:TEXT_MAX]
    if d.get("gif") and not fdata:              # GIF из «Моих GIF» (s<id>) или из поиска (g<id>) — уходит обычным вложением
        import forum_gifs
        fdata, fmime, fname = await forum_gifs.for_send(me, d.get("gif"))
    try:
        voice = B.parse_voice(d, fdata, fmime)
        note = None if voice else B.parse_note(d, fdata, fmime)
    except B.ApiError:
        raise FErr(400, "bad_voice", "Не удалось отправить запись")
    attach = None
    if voice or note:
        text = ""
    elif fdata:
        if "." in fname and fname.rsplit(".", 1)[-1].lower() in B.BAD_EXT:
            raise FErr(400, "bad_file", "Такие файлы отправлять нельзя")
        if fname.lower().startswith(("voice.", "circle.")):
            fname = "file_" + fname
        _, amime = F.attach_info(fname, fmime)
        attach = (amime, fname)
    sid = to_int(d.get("sticker_id"))
    sticker = None
    if sid:
        if text or voice or note or attach:
            raise FErr(400, "bad_message")
        sticker = await _sticker_for_send(sid)
    if not text and not voice and not note and not attach and not sticker:
        raise FErr(400, "bad_message")
    check_text(text)
    if not B.rate_ok(("fgm", me), 0.5):
        raise FErr(429, "too_fast", "Не так быстро")
    reply_to = reply_author = None
    rt = to_int(d.get("reply_to"))
    if rt:
        reply_author = await P().fetchval("SELECT sender_id FROM forum_group_msgs WHERE id=$1 AND group_id=$2", rt, gid)
        reply_to = rt if reply_author else None
    if voice or note:
        vmime, vname, vdur = (voice[:3] if voice else note)
        vwave = voice[3] if voice else None
        mid = await P().fetchval(
            """INSERT INTO forum_group_msgs(group_id,sender_id,body,file_data,file_mime,file_name,file_size,voice_dur,voice_wave,reply_to)
               VALUES($1,$2,'',$3,$4,$5,$6,$7,$8,$9) RETURNING id""", gid, me, fdata, vmime, vname, len(fdata), vdur, vwave, reply_to)
    elif attach:
        mid = await P().fetchval(
            """INSERT INTO forum_group_msgs(group_id,sender_id,body,file_data,file_mime,file_name,file_size,reply_to)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""", gid, me, text, fdata, attach[0], attach[1], len(fdata), reply_to)
    else:
        mid = await P().fetchval(
            "INSERT INTO forum_group_msgs(group_id,sender_id,body,reply_to,sticker_id) VALUES($1,$2,$3,$4,$5) RETURNING id",
            gid, me, text, reply_to, sticker["id"] if sticker else None)
    await P().execute("UPDATE forum_group_members SET last_read=GREATEST(last_read,$3) WHERE group_id=$1 AND user_id=$2", gid, me, mid)
    _gtyping.pop((gid, me), None)
    asyncio.create_task(_safe(_notify_mentions(gid, me, mid, text, reply_author)))
    import forum_fcm
    if forum_fcm.enabled():                       # системный push участникам (кроме тех, у кого чат «без звука»)
        fa = voice or note or attach              # (mime, имя, …)
        forum_fcm.spawn(forum_fcm.group_msg(gid, me, c.g["title"], text, fa[1] if fa else None, fa[0] if fa else None,
                                            bool(sticker), c.channel))
    return J({"ok": True, "id": mid})


async def _own_msg(me, gid, mid, c, need_own=False):
    r = await P().fetchrow(f"SELECT {MSG_COLS} FROM forum_group_msgs m WHERE m.id=$1 AND m.group_id=$2", to_int(mid), gid)
    if not r:
        raise FErr(404, "not_found", "Сообщение не найдено")
    if need_own and r["sender_id"] != me:
        raise FErr(403, "forbidden", "Можно изменять только свои сообщения")
    return r


@api
async def a_gmsg_edit(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("gid"))
    c = await ctx(me, gid, "post")
    r = await _own_msg(me, gid, d.get("id"), c, need_own=True)
    if r["voice_dur"] or r["sticker_id"]:
        raise FErr(400, "bad_message", "Это сообщение изменить нельзя")
    text = str(d.get("text") or "").strip()[:TEXT_MAX]
    if not text and not r["has_file"]:
        raise FErr(400, "empty", "Сообщение не может быть пустым")
    check_text(text)
    await P().execute("UPDATE forum_group_msgs SET body=$2,edited_at=now() WHERE id=$1", r["id"], text)
    reply_author = await P().fetchval("SELECT sender_id FROM forum_group_msgs WHERE id=$1", r["reply_to"]) if r["reply_to"] else None
    # уведомляем только тех, кого в прошлой версии не упоминали
    old = {x["user_id"] for x in await P().fetch("SELECT user_id FROM forum_group_mentions WHERE msg_id=$1", r["id"])}
    for uid, kind in (await _mention_targets(gid, me, text, reply_author)).items():
        if uid not in old:
            await P().execute("INSERT INTO forum_group_mentions(msg_id,user_id,group_id) VALUES($1,$2,$3) ON CONFLICT DO NOTHING", r["id"], uid, gid)
            await F.notify(uid, kind, me, group_id=gid, msg_id=r["id"])
    return J({"ok": True})


@api
async def a_gmsg_delete(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("gid"))
    c = await ctx(me, gid, "see")
    ids = d.get("ids") if isinstance(d.get("ids"), list) else [d.get("id")]
    for_all = bool(d.get("for_all"))
    for mid in [to_int(x) for x in ids[:50]]:
        r = await P().fetchrow("SELECT id,sender_id FROM forum_group_msgs WHERE id=$1 AND group_id=$2", mid, gid)
        if not r:
            continue
        if for_all and (r["sender_id"] == me or c.admin):
            await P().execute("DELETE FROM forum_group_msgs WHERE id=$1", mid)
        else:
            await P().execute("INSERT INTO forum_group_hidden(user_id,msg_id) VALUES($1,$2) ON CONFLICT DO NOTHING", me, mid)
    return J({"ok": True})


@api
async def a_gmsg_pin(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("gid"))
    c = await ctx(me, gid, "admin")
    r = await _own_msg(me, gid, d.get("id"), c)
    if d.get("pin", True):
        if await P().fetchval("SELECT count(*) FROM forum_group_msgs WHERE group_id=$1 AND pinned_at IS NOT NULL", gid) >= MAX_PINS and not r["pinned_at"]:
            raise FErr(400, "too_many_pins", "Закреплено слишком много сообщений")
        await P().execute("UPDATE forum_group_msgs SET pinned_at=now() WHERE id=$1", r["id"])
    else:
        await P().execute("UPDATE forum_group_msgs SET pinned_at=NULL WHERE id=$1", r["id"])
    return J({"ok": True})


@api
async def a_gmsg_react(request):
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("gid"))
    await ctx(me, gid, "member")
    mid = to_int(d.get("id"))
    emoji = str(d.get("emoji") or "").strip()
    if emoji and emoji not in F.MSG_REACTIONS:
        raise FErr(400, "bad_emoji", "Такой реакции нет")
    if not mid or not await P().fetchval("SELECT 1 FROM forum_group_msgs WHERE id=$1 AND group_id=$2", mid, gid):
        raise FErr(404, "not_found", "Сообщение не найдено")
    if not bm().rate_ok(("fgrx", me), 0.25):
        raise FErr(429, "too_fast", "Не так быстро")
    cur = await P().fetchval("SELECT emoji FROM forum_group_rx WHERE msg_id=$1 AND user_id=$2", mid, me)
    if not emoji or emoji == cur:
        await P().execute("DELETE FROM forum_group_rx WHERE msg_id=$1 AND user_id=$2", mid, me)
        mine = None
    else:
        await P().execute(
            "INSERT INTO forum_group_rx(msg_id,user_id,emoji) VALUES($1,$2,$3) ON CONFLICT(msg_id,user_id) DO UPDATE SET emoji=EXCLUDED.emoji, created_at=now()", mid, me, emoji)
        mine = emoji
    return J({"ok": True, "mine": mine})


@api
async def a_gmsg_heard(request):
    me = request["fuid"]
    mid = to_int((await jbody(request)).get("id"))
    if mid and await P().fetchval(
            "SELECT 1 FROM forum_group_msgs m JOIN forum_group_members gm ON gm.group_id=m.group_id AND gm.user_id=$2 WHERE m.id=$1 AND m.voice_dur IS NOT NULL", mid, me):
        await P().execute("INSERT INTO forum_group_heard(msg_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING", mid, me)
    return J({"ok": True})


@api
async def a_gtyping(request):
    d = await jbody(request)
    gid = to_int(d.get("id"))
    me = request["fuid"]
    if gid and await P().fetchval("SELECT 1 FROM forum_group_members WHERE group_id=$1 AND user_id=$2", gid, me):
        if len(_gtyping) > 3000:
            _gtyping.clear()
        _gtyping[(gid, me)] = (time.monotonic(), {"rec": "rec", "vid": "vid"}.get(d.get("kind"), "typ"))
    return J({"ok": True})


@api
async def a_gmsg_forward(request):
    """Переслать сообщения ИЗ группы: в личный чат (to_kind=user) или в другую группу (to_kind=group)."""
    me = request["fuid"]
    d = await jbody(request)
    gid = to_int(d.get("gid"))
    await ctx(me, gid, "see")
    ids = sorted({to_int(x) for x in (d.get("ids") if isinstance(d.get("ids"), list) else [])[:20] if to_int(x)})
    to = to_int(d.get("to"))
    if not ids or not to:
        raise FErr(400, "bad_peer")
    ok_ids = [r["id"] for r in await P().fetch(
        f"SELECT m.id FROM forum_group_msgs m WHERE m.id=ANY($2::bigint[]) AND m.group_id=$3 AND {NOT_HIDDEN} ORDER BY m.id", me, ids, gid)]
    if d.get("to_kind") == "group":
        await ctx(me, to, "post")
        for i in ok_ids:
            await P().execute(
                """INSERT INTO forum_group_msgs(group_id,sender_id,body,file_data,file_mime,file_name,file_size,voice_dur,voice_wave,fwd_from,sticker_id)
                   SELECT $1,$2,body,file_data,file_mime,file_name,file_size,voice_dur,voice_wave,COALESCE(fwd_from,sender_id),sticker_id FROM forum_group_msgs WHERE id=$3""", to, me, i)
    else:
        if to == me or not await P().fetchval("SELECT 1 FROM users WHERE user_id=$1", to):
            raise FErr(404, "not_found", "Пользователь не найден")
        if not await _can_dm(me, to):
            raise FErr(403, "blocked", "Сообщения недоступны (блокировка)")
        for i in ok_ids:
            mid = await P().fetchval(
                """INSERT INTO direct_messages(sender_id,recipient_id,body,file_data,file_mime,file_name,file_size,fwd_from,voice_dur,voice_wave)
                   SELECT $1,$2,body,file_data,file_mime,file_name,file_size,COALESCE(fwd_from,sender_id),voice_dur,voice_wave FROM forum_group_msgs WHERE id=$3 RETURNING id""", me, to, i)
            sid = await P().fetchval("SELECT sticker_id FROM forum_group_msgs WHERE id=$1", i)
            if sid and mid:
                await P().execute("INSERT INTO forum_msg_stickers(msg_id,sticker_id) VALUES($1,$2) ON CONFLICT DO NOTHING", mid, sid)
        if ok_ids:
            F.push_dm_all(me, to, None, "↪️ Пересланное сообщение", None, None)
    return J({"ok": True, "count": len(ok_ids)})


@api
async def a_gforward_in(request):
    """Переслать сообщения ИЗ личного чата в группу или канал."""
    me = request["fuid"]
    d = await jbody(request)
    to = to_int(d.get("to"))
    await ctx(me, to, "post")
    ids = sorted({to_int(x) for x in (d.get("ids") if isinstance(d.get("ids"), list) else [])[:20] if to_int(x)})
    rows = await P().fetch(
        """SELECT id FROM direct_messages WHERE id=ANY($2::bigint[]) AND (sender_id=$1 OR recipient_id=$1) AND deal_id IS NULL
           AND NOT EXISTS(SELECT 1 FROM dm_hidden h WHERE h.user_id=$1 AND h.msg_id=direct_messages.id) ORDER BY id""", me, ids)
    for r in rows:
        await P().execute(
            """INSERT INTO forum_group_msgs(group_id,sender_id,body,file_data,file_mime,file_name,file_size,voice_dur,voice_wave,fwd_from,sticker_id)
               SELECT $1,$2,body,file_data,file_mime,file_name,file_size,voice_dur,voice_wave,COALESCE(fwd_from,sender_id),
                 (SELECT sticker_id FROM forum_msg_stickers WHERE msg_id=direct_messages.id) FROM direct_messages WHERE id=$3""", to, me, r["id"])
    return J({"ok": True, "count": len(rows)})


async def a_gfile(request):
    """Файлы, голосовые и кружки групп — по подписанной ссылке (как /img/dm/ID)."""
    mid = to_int(request.match_info.get("mid"))
    B = bm()
    if not mid or not hmac.compare_digest(request.query.get("t", ""), file_sig(mid)):
        raise web.HTTPNotFound()
    row = await P().fetchrow("SELECT file_data,file_mime,file_name FROM forum_group_msgs WHERE id=$1", mid)
    if not row or not row["file_data"]:
        raise web.HTTPNotFound()
    data, mime, name = bytes(row["file_data"]), row["file_mime"], row["file_name"] or ""
    hdr = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    if B.voice_mime(mime) and name.startswith("voice."):
        return B.ranged_audio(request, data, B.voice_mime(mime), hdr)
    if B.note_mime(mime) and name.startswith("circle."):
        return B.ranged_audio(request, data, B.note_mime(mime), hdr)
    if mime in B.IMG_MIMES:
        return web.Response(body=data, content_type=mime, headers=hdr)
    if mime in F.VIDEO_MIMES:
        return B.ranged_audio(request, data, mime, hdr)
    from urllib.parse import quote
    hdr["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(name or "file")
    return web.Response(body=data, content_type="application/octet-stream", headers=hdr)


# ============================================================================ стикеры и эмодзи-паки
def _img_mime(data):
    """Тип по содержимому: PNG (в т.ч. APNG) / JPEG / GIF / WebP (в т.ч. анимированный) / WebM (видео-стикер)."""
    if data[:4] == b"\x1a\x45\xdf\xa3" and b"webm" in data[:64]:
        return "video/webm"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_anim(data, mime):
    """Анимация ли это: WebM и GIF — да; WebP — по флагу анимации в VP8X; PNG — по блоку acTL (APNG) до данных."""
    if mime in ("video/webm", "image/gif"):
        return True
    if mime == "image/webp":
        return data[12:16] == b"VP8X" and len(data) > 20 and bool(data[20] & 2)
    if mime == "image/png":
        pos = 8
        while pos + 8 <= len(data):
            n, t = int.from_bytes(data[pos:pos + 4], "big"), data[pos + 4:pos + 8]
            if t == b"acTL":
                return True
            if t in (b"IDAT", b"IEND"):
                return False
            pos += 12 + n
    return False


async def _sticker_for_send(sid):
    st = await P().fetchrow(
        "SELECT s.id,s.emoji,p.kind FROM forum_stickers s JOIN forum_stickerpacks p ON p.id=s.pack_id AND NOT p.deleted WHERE s.id=$1", sid)
    if not st or st["kind"] != "sticker":
        raise FErr(404, "not_found", "Стикер не найден")
    return st


async def _pack(me, pid, own=False):
    r = await P().fetchrow("SELECT id,owner_id,title,kind,is_public,code,created_at FROM forum_stickerpacks WHERE id=$1 AND NOT deleted", pid)
    if not r:
        raise FErr(404, "not_found", "Набор не найден")
    if own and r["owner_id"] != me and not await F.is_staff(me):
        raise FErr(403, "forbidden", "Это чужой набор")
    return r


async def _packs_json(me, rows, items=True):
    ids = [r["id"] for r in rows]
    its = {}
    if ids and items:
        for q in await P().fetch("SELECT id,pack_id,emoji FROM forum_stickers WHERE pack_id=ANY($1::int[]) ORDER BY pos,id", ids):
            its.setdefault(q["pack_id"], []).append({"id": q["id"], "e": q["emoji"]})
    cnt = {}
    if ids and not items:
        for q in await P().fetch("SELECT pack_id,count(*)::int n,(array_agg(id ORDER BY pos,id))[1] cv FROM forum_stickers WHERE pack_id=ANY($1::int[]) GROUP BY pack_id", ids):
            cnt[q["pack_id"]] = (q["n"], q["cv"])
    um = await users_map([r["owner_id"] for r in rows])
    pn = await N.get_many("pack", ids)
    added = {q["pack_id"] for q in await P().fetch("SELECT pack_id FROM forum_user_packs WHERE user_id=$1 AND pack_id=ANY($2::int[])", me, ids)} if ids else set()
    out = []
    for r in rows:
        lst = its.get(r["id"], [])
        o = {"id": r["id"], "title": r["title"], "kind": r["kind"], "public": bool(r["is_public"]), "mine": r["owner_id"] == me,
             "owner": (um.get(r["owner_id"]) or ghost(r["owner_id"]))["name"], "added": r["id"] in added,
             "username": pn.get(r["id"])}
        if items:
            o["items"], o["n"], o["cover"] = lst, len(lst), (lst[0]["id"] if lst else None)
        else:
            o["n"], o["cover"] = cnt.get(r["id"], (0, None))
        out.append(o)
    return out


@api
async def a_stk_mine(request):
    me = request["fuid"]
    rows = await P().fetch(
        """SELECT p.id,p.owner_id,p.title,p.kind,p.is_public,p.code,p.created_at FROM forum_user_packs up
           JOIN forum_stickerpacks p ON p.id=up.pack_id AND NOT p.deleted WHERE up.user_id=$1 ORDER BY up.added_at DESC""", me)
    return J({"packs": await _packs_json(me, rows)})


@api
async def a_stk_find(request):
    me = request["fuid"]
    q = (request.query.get("q") or "").strip().lstrip("@")[:40]
    kind = request.query.get("kind")
    cols = "p.id,p.owner_id,p.title,p.kind,p.is_public,p.code,p.created_at"
    args, where = [], "p.is_public AND NOT p.deleted AND EXISTS(SELECT 1 FROM forum_stickers s WHERE s.pack_id=p.id)"
    if q:
        args.append(F._like(q))
        where += " AND (p.title ILIKE $%d OR p.id IN (SELECT ref FROM forum_names WHERE kind='pack' AND name ILIKE $%d))" % (len(args), len(args))
    if kind in ("sticker", "emoji"):
        args.append(kind)
        where += " AND p.kind=$%d" % len(args)
    rows = await P().fetch(
        f"SELECT {cols} FROM forum_stickerpacks p WHERE {where} ORDER BY (SELECT count(*) FROM forum_user_packs u WHERE u.pack_id=p.id) DESC, p.id DESC LIMIT 40", *args)
    return J({"packs": await _packs_json(me, rows, items=False)})


@api
async def a_stk_pack(request):
    me = request["fuid"]
    r = await _pack(me, to_int(request.query.get("id")))
    if not r["is_public"] and r["owner_id"] != me and not await P().fetchval(
            "SELECT 1 FROM forum_user_packs WHERE user_id=$1 AND pack_id=$2", me, r["id"]) and \
            N.clean(request.query.get("name")) != (await N.get("pack", r["id"]) or "\0"):
        raise FErr(403, "forbidden", "Набор закрытый — откройте его по ссылке")
    return J({"pack": (await _packs_json(me, [r]))[0]})


@api
async def a_stk_pack_create(request):
    me = request["fuid"]
    d = await jbody(request)
    kind = "emoji" if d.get("kind") == "emoji" else "sticker"
    n_own = await P().fetchval("SELECT count(*) FROM forum_stickerpacks WHERE owner_id=$1 AND NOT deleted", me)
    if n_own >= PACKS_OWNED:
        raise FErr(400, "limit", "Можно создать не больше %d наборов" % PACKS_OWNED)
    if not bm().rate_ok(("fpackc", me), 2):
        raise FErr(429, "too_fast", "Не так быстро")
    # название необязательно: «Мои стикеры», «Мои стикеры 2» … — переименовать можно на странице набора
    title = str(d.get("title") or "").strip()[:40] or ("Мои эмодзи" if kind == "emoji" else "Мои стикеры") + (" %d" % (n_own + 1) if n_own else "")
    pid = await P().fetchval(
        "INSERT INTO forum_stickerpacks(owner_id,title,kind,is_public,code) VALUES($1,$2,$3,$4,$5) RETURNING id",
        me, title, kind, d.get("public", True) is not False, secrets.token_hex(5))
    await P().execute("INSERT INTO forum_user_packs(user_id,pack_id) VALUES($1,$2) ON CONFLICT DO NOTHING", me, pid)
    await N.auto("pack", pid)                      # ссылка exg/имя появляется сразу
    return J({"ok": True, "id": pid})


@api
async def a_stk_pack_update(request):
    me = request["fuid"]
    d = await jbody(request)
    r = await _pack(me, to_int(d.get("id")), own=True)
    title = str(d.get("title", r["title"]) or "").strip()[:40]
    if not title:
        raise FErr(400, "empty", "Введите название набора")
    uname = await N.check(d["username"], "pack", r["id"]) if str(d.get("username") or "").strip() else None
    await P().execute("UPDATE forum_stickerpacks SET title=$2,is_public=$3 WHERE id=$1", r["id"], title, bool(d["public"]) if "public" in d else bool(r["is_public"]))
    if uname:
        await N.put("pack", r["id"], uname)
    return J({"ok": True})


@api
async def a_stk_pack_delete(request):
    me = request["fuid"]
    r = await _pack(me, to_int((await jbody(request)).get("id")), own=True)
    await P().execute("UPDATE forum_stickerpacks SET deleted=TRUE WHERE id=$1", r["id"])   # старые сообщения со стикером остаются
    await N.drop("pack", r["id"])
    return J({"ok": True})


@api
async def a_stk_item_add(request):
    me = request["fuid"]
    form = await request.post()
    r = await _pack(me, to_int(form.get("pack_id")), own=True)
    f = form.get("file")
    if f is None or not hasattr(f, "file"):
        raise FErr(400, "no_file", "Файл не выбран")
    data = f.file.read()
    mime = _img_mime(data) if data else None
    emo = r["kind"] == "emoji"
    anim = bool(mime) and _is_anim(data, mime)
    cap = (EMO_ANIM_MAX if anim else EMO_MAX) if emo else (STK_ANIM_MAX if anim else STK_MAX)
    if not mime or len(data) > cap:
        raise FErr(400, "bad_image", ("Анимация слишком большая — до %d КБ" if anim else "Нужна картинка (PNG, WebP, GIF, JPEG) или анимация (WebM, WebP, GIF) до %d КБ") % (cap // 1024))
    if await P().fetchval("SELECT count(*) FROM forum_stickers WHERE pack_id=$1", r["id"]) >= (EMO_PER_PACK if emo else STK_PER_PACK):
        raise FErr(400, "limit", "В наборе не больше %d картинок" % (EMO_PER_PACK if emo else STK_PER_PACK))
    emoji = str(form.get("emoji") or "").strip()[:8]
    sid = await P().fetchval(
        "INSERT INTO forum_stickers(pack_id,data,mime,emoji,pos) VALUES($1,$2,$3,$4,(SELECT coalesce(max(pos),0)+1 FROM forum_stickers WHERE pack_id=$1)) RETURNING id",
        r["id"], data, mime, emoji)
    return J({"ok": True, "id": sid})


@api
async def a_stk_of(request):
    """Тап по стикеру в чате: какому набору он принадлежит (и имя набора — по нему открывается даже закрытый набор)."""
    sid = to_int(request.query.get("id"))
    pid = await P().fetchval("SELECT p.id FROM forum_stickers s JOIN forum_stickerpacks p ON p.id=s.pack_id AND NOT p.deleted WHERE s.id=$1", sid)
    if not pid:
        raise FErr(404, "not_found", "Набор этого стикера удалён")
    return J({"pack": pid, "name": await N.get("pack", pid)})


@api
async def a_stk_item_update(request):
    """Привязать смайлик к стикеру (он подписывает стикер в списке чатов)."""
    me = request["fuid"]
    d = await jbody(request)
    sid = to_int(d.get("id"))
    pid = await P().fetchval("SELECT pack_id FROM forum_stickers WHERE id=$1", sid)
    if not pid:
        raise FErr(404, "not_found", "Не найдено")
    await _pack(me, pid, own=True)
    await P().execute("UPDATE forum_stickers SET emoji=$2 WHERE id=$1", sid, str(d.get("emoji") or "").strip()[:8])
    return J({"ok": True})


@api
async def a_stk_item_delete(request):
    me = request["fuid"]
    sid = to_int((await jbody(request)).get("id"))
    pid = await P().fetchval("SELECT pack_id FROM forum_stickers WHERE id=$1", sid)
    if not pid:
        raise FErr(404, "not_found", "Не найдено")
    await _pack(me, pid, own=True)
    await P().execute("DELETE FROM forum_stickers WHERE id=$1", sid)
    return J({"ok": True})


@api
async def a_stk_add(request):
    me = request["fuid"]
    d = await jbody(request)
    link = str(d.get("name") or "").strip()
    pid = to_int(d.get("id"))
    if link:                                       # exg/имя, @имя или полная ссылка; по ссылке можно добавить и закрытый набор
        found = await N.resolve(link)
        if not found or found["kind"] != "pack":
            raise FErr(404, "not_found", "Набор по этой ссылке не найден")
        pid = found["id"]
    r = await _pack(me, pid)
    if not r["is_public"] and not link and r["owner_id"] != me:
        raise FErr(403, "forbidden", "Набор закрытый — нужна ссылка")
    if await P().fetchval("SELECT count(*) FROM forum_user_packs WHERE user_id=$1", me) >= PACKS_ADDED:
        raise FErr(400, "limit", "Можно добавить не больше %d наборов" % PACKS_ADDED)
    await P().execute("INSERT INTO forum_user_packs(user_id,pack_id) VALUES($1,$2) ON CONFLICT DO NOTHING", me, r["id"])
    return J({"ok": True, "id": r["id"]})


@api
async def a_stk_remove(request):
    me = request["fuid"]
    await P().execute("DELETE FROM forum_user_packs WHERE user_id=$1 AND pack_id=$2", me, to_int((await jbody(request)).get("id")))
    return J({"ok": True})


async def a_stk_img(request):
    r = await P().fetchrow(
        "SELECT s.data,s.mime FROM forum_stickers s JOIN forum_stickerpacks p ON p.id=s.pack_id WHERE s.id=$1", to_int(request.match_info.get("sid")))
    if not r:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(r["data"]), content_type=r["mime"],
                        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


async def backfill_names():
    """Наборам, созданным до ссылок exg/имя, выдаём имя."""
    rows = await P().fetch(
        "SELECT p.id FROM forum_stickerpacks p WHERE NOT p.deleted AND NOT EXISTS(SELECT 1 FROM forum_names n WHERE n.kind='pack' AND n.ref=p.id)")
    for r in rows:
        await N.auto("pack", r["id"])


# ============================================================================ подключение
def install(r, A):
    r.add_get(A + "/groups/find", a_gfind)
    r.add_get(A + "/groups/board", a_gboard)
    r.add_post(A + "/groups/create", a_gcreate)
    r.add_post(A + "/groups/join", a_gjoin)
    r.add_post(A + "/groups/leave", a_gleave)
    r.add_post(A + "/groups/delete", a_gdelete)
    r.add_get(A + "/groups/info", a_ginfo)
    r.add_get(A + "/groups/members", a_gmembers)
    r.add_get(A + "/groups/mention", a_gmention)
    r.add_post(A + "/groups/update", a_gupdate)
    r.add_post(A + "/groups/avatar", a_gavatar_set)
    r.add_get(A + "/groups/avatar/{gid}", a_gavatar)
    r.add_post(A + "/groups/add", a_gadd)
    r.add_post(A + "/groups/kick", a_gkick)
    r.add_post(A + "/groups/role", a_grole)
    r.add_post(A + "/groups/pref", a_gpref)
    r.add_get(A + "/groups/messages", a_gmessages)
    r.add_post(A + "/groups/send", a_gsend)
    r.add_post(A + "/groups/typing", a_gtyping)
    r.add_post(A + "/groups/msg/edit", a_gmsg_edit)
    r.add_post(A + "/groups/msg/delete", a_gmsg_delete)
    r.add_post(A + "/groups/msg/pin", a_gmsg_pin)
    r.add_post(A + "/groups/msg/react", a_gmsg_react)
    r.add_post(A + "/groups/msg/heard", a_gmsg_heard)
    r.add_post(A + "/groups/msg/forward", a_gmsg_forward)
    r.add_post(A + "/groups/forward_in", a_gforward_in)
    r.add_get(A + "/groups/file/{mid}", a_gfile)
    r.add_get(A + "/stickers/mine", a_stk_mine)
    r.add_get(A + "/stickers/find", a_stk_find)
    r.add_get(A + "/stickers/pack", a_stk_pack)
    r.add_post(A + "/stickers/pack", a_stk_pack_create)
    r.add_post(A + "/stickers/pack/update", a_stk_pack_update)
    r.add_post(A + "/stickers/pack/delete", a_stk_pack_delete)
    r.add_post(A + "/stickers/item", a_stk_item_add)
    r.add_get(A + "/stickers/of", a_stk_of)
    r.add_post(A + "/stickers/item/update", a_stk_item_update)
    r.add_post(A + "/stickers/item/delete", a_stk_item_delete)
    r.add_post(A + "/stickers/add", a_stk_add)
    r.add_post(A + "/stickers/remove", a_stk_remove)
    r.add_get(A + "/stickers/img/{sid}", a_stk_img)
