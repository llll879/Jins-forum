# -*- coding: utf-8 -*-
"""
KMBP FORUM — внутренние юзернеймы и короткие ссылки вида  exg/имя  (как t.me/имя в Telegram).

Одно общее пространство имён на всё: профили, группы, каналы и наборы стикеров/эмодзи. Имя уникально среди всех.
  • профиль  — exg/имя открывает профиль (имя можно сменить в «Изменить профиль»; без него работает ник из Telegram);
  • группа / канал — exg/имя у ПУБЛИЧНЫХ чатов (необязательно); у закрытых — приглашение exg/+токен, его видят админы;
  • набор стикеров / эмодзи — имя создаётся само при создании набора, потом его можно поменять.
Открытие в браузере: /exg/имя → редирект в приложение (/forum#/n/имя); внутри приложения ссылки в тексте кликабельны.

Имя: 4–32 символа, латиница, цифры и «_», первая — буква, регистр не важен.
"""
from __future__ import annotations

import re
import secrets

DDL = """
CREATE TABLE IF NOT EXISTS forum_names(
    name TEXT PRIMARY KEY, kind TEXT NOT NULL, ref BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS forum_names_ref_idx ON forum_names(kind, ref);
"""

KINDS = ("user", "group", "pack")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{3,31}$")
RESERVED = {
    "exg", "forum", "admin", "admins", "support", "system", "api", "app", "bot", "kmbp", "jins", "news", "help", "root", "login",
    "settings", "stickers", "sticker", "emoji", "group", "groups", "channel", "channels", "chat", "chats", "search", "profile",
    "null", "none", "undefined", "telegram", "moderator", "moderators", "official",
}
_ALPH = "abcdefghjkmnpqrstuvwxyz23456789"
_URL_HEAD = re.compile(r"^(?:https?://[^/\s]+/)?(?:forum/)?(?:exg/)?", re.I)


def _F():
    import forum                      # лениво: модуль форума подключает нас же
    return forum


def clean(raw):
    """«https://хост/exg/Имя», «exg/Имя», «@Имя», «+токен» → «имя» / «+токен» (нижний регистр, без хвоста)."""
    s = str(raw or "").strip()
    s = s.split("?")[0].split("#")[0] if re.match(r"^https?://", s, re.I) else s
    s = _URL_HEAD.sub("", s).strip().strip("/").lstrip("@")
    return s.lower()[:40]


def invite_token(s):
    """Для «+abc123» возвращает «abc123», иначе None."""
    return s[1:] if s.startswith("+") and re.fullmatch(r"\+[a-z0-9]{4,32}", s) else None


def valid(name):
    """Текст ошибки для плохого имени или None, если имя годится."""
    if not name:
        return "Введите имя"
    if len(name) < 4:
        return "Минимум 4 символа"
    if len(name) > 32:
        return "Максимум 32 символа"
    if not re.fullmatch(r"[a-z0-9_]+", name):
        return "Только латиница, цифры и «_»"
    if not name[0].isalpha():
        return "Имя должно начинаться с буквы"
    if name in RESERVED:
        return "Это имя зарезервировано"
    return None


async def _alive(kind, ref):
    P = _F().P
    if kind == "user":
        return bool(await P().fetchval("SELECT 1 FROM users WHERE user_id=$1", ref))
    if kind == "group":
        return bool(await P().fetchval("SELECT 1 FROM forum_groups WHERE id=$1 AND NOT deleted", ref))
    if kind == "pack":
        return bool(await P().fetchval("SELECT 1 FROM forum_stickerpacks WHERE id=$1 AND NOT deleted", ref))
    return False


async def get(kind, ref):
    return await _F().P().fetchval("SELECT name FROM forum_names WHERE kind=$1 AND ref=$2", kind, int(ref))


async def get_many(kind, ids):
    ids = list({int(i) for i in ids if i})
    if not ids:
        return {}
    rows = await _F().P().fetch("SELECT ref,name FROM forum_names WHERE kind=$1 AND ref=ANY($2::bigint[])", kind, ids)
    return {r["ref"]: r["name"] for r in rows}


async def taken_error(name, kind, ref):
    """Текст ошибки, если имя занято кем-то другим, иначе None."""
    P = _F().P
    row = await P().fetchrow("SELECT kind,ref FROM forum_names WHERE name=$1", name)
    if row and not (row["kind"] == kind and row["ref"] == int(ref or 0)):
        if await _alive(row["kind"], row["ref"]):
            return "Это имя уже занято"
        await P().execute("DELETE FROM forum_names WHERE name=$1", name)          # хозяин удалён — имя свободно
    # чужой ник из Telegram тоже занят (чтобы не выдавать себя за другого)
    if await P().fetchval("SELECT 1 FROM users WHERE lower(username)=$1 AND user_id<>$2", name, int(ref) if kind == "user" else 0):
        return "Это имя уже занято"
    return None


async def check(raw, kind, ref):
    """Проверяет имя и возвращает его в нормальном виде; при проблеме кидает FErr(400/409)."""
    FErr = _F().FErr
    name = clean(raw)
    err = valid(name)
    if err:
        raise FErr(400, "bad_name", err)
    err = await taken_error(name, kind, ref)
    if err:
        raise FErr(409, "name_taken", err)
    return name


async def put(kind, ref, name):
    """Закрепляет имя за объектом (прежнее имя освобождается). Пустое имя — снимает."""
    P, FErr = _F().P, _F().FErr
    if not name:
        await drop(kind, ref)
        return
    try:
        await P().execute(
            "INSERT INTO forum_names(name,kind,ref) VALUES($1,$2,$3) ON CONFLICT (kind,ref) DO UPDATE SET name=EXCLUDED.name, created_at=now()",
            name, kind, int(ref))
    except Exception as e:
        if getattr(e, "sqlstate", None) == "23505":
            raise FErr(409, "name_taken", "Это имя уже занято")
        raise


async def drop(kind, ref):
    await _F().P().execute("DELETE FROM forum_names WHERE kind=$1 AND ref=$2", kind, int(ref))


async def auto(kind, ref):
    """Случайное короткое имя (для наборов стикеров: ссылка появляется сразу, поменять можно потом)."""
    for _ in range(12):
        nm = secrets.choice("abcdefghjkmnpqrstuvwxyz") + "".join(secrets.choice(_ALPH) for _ in range(5))
        if valid(nm) is None and not await taken_error(nm, kind, ref):
            try:
                await put(kind, ref, nm)
                return nm
            except Exception:
                continue
    return None


async def resolve(raw):
    """Имя / ссылка → {"kind","id",...} или None. «+токен» — приглашение в группу."""
    P = _F().P
    s = clean(raw)
    tok = invite_token(s)
    if tok:
        gid = await P().fetchval("SELECT id FROM forum_groups WHERE invite=$1 AND NOT deleted", tok)
        return {"kind": "group", "id": gid, "via": "invite", "invite": tok} if gid else None
    if not s:
        return None
    row = await P().fetchrow("SELECT kind,ref FROM forum_names WHERE name=$1", s)
    if row and await _alive(row["kind"], row["ref"]):
        return {"kind": row["kind"], "id": row["ref"], "via": "name"}
    uid = await P().fetchval("SELECT user_id FROM users WHERE lower(username)=$1 AND user_id>0 ORDER BY last_seen DESC NULLS LAST LIMIT 1", s)
    return {"kind": "user", "id": uid, "via": "tg"} if uid else None
