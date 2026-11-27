# -*- coding: utf-8 -*-
"""
BAZAR — отдельный сервис (точка входа). Запуск: python main.py

Форум работает в той же БД, что и бот (DATABASE_URL общий), но как самостоятельный процесс:
  • НЕ запускает polling бота (этим занят основной сервис jins-bot) — только отправляет сообщения тем же токеном
    (пуши о комментариях/ЛС, жалобы в админ-группу, вызов оператора);
  • отдаёт /forum, /forum/api/*, /exg/<имя>; /health — для хостинга и «будилки».
Таблицы users, direct_messages и т.д. создаёт бот при первом запуске — поэтому основной сервис нужно запустить ПЕРВЫМ
(форум сам подождёт, пока они появятся).
"""
import asyncio
import logging
import os
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import ClientSession, ClientTimeout, web

import botcore          # общие функции бота (профили, ЛС, значки, пуши) — сгенерировано из bot.py
import forum
import support

log = logging.getLogger("jins.forum.main")
PORT = int(os.getenv("PORT", "10000"))


async def health(request):
    return web.Response(text="forum ok")


async def wait_for_core_tables():
    """Форум стартует после бота: ждём, пока тот создаст users и direct_messages (на пустой БД бот делает это при первом запуске)."""
    waited = 0
    while True:
        ok = await botcore.pool.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_name IN ('users','direct_messages','settings','admins')")
        if ok == 4:
            return
        if waited % 30 == 0:
            log.warning("Ждём, пока основной сервис (jins-bot) создаст таблицы в БД… запустите его первым.")
        await asyncio.sleep(5)
        waited += 5


async def keepalive():
    """«Будилка» для бесплатных хостингов, которые усыпляют сервис: пингует собственный адрес. Нужен FORUM_URL (https://...)."""
    url = (os.getenv("FORUM_URL") or "").rstrip("/")
    if not url or os.getenv("FORUM_KEEPALIVE", "1") in ("0", "false", "no"):
        log.info("keep-alive выключен (FORUM_URL не задан или FORUM_KEEPALIVE=0)")
        return
    while True:
        await asyncio.sleep(600)
        try:
            async with botcore.HTTP.get(url + "/health", timeout=ClientTimeout(total=20)) as resp:
                log.info("keep-alive %s", resp.status)
        except Exception as e:
            log.warning("keep-alive failed: %s", e)


async def main():
    await botcore.init_pool()
    await wait_for_core_tables()
    botcore.HTTP = ClientSession(timeout=ClientTimeout(total=30))
    bm = sys.modules["botcore"]

    bot = Bot(botcore.BOT_TOKEN, session=botcore.SafeSession(),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    botcore._BOT = bot
    try:
        botcore.BOT_USERNAME = (await bot.get_me()).username or ""
    except Exception:
        log.exception("get_me failed")

    await support.start(bm)
    await forum.start(bm)

    app = web.Application(client_max_size=22 * 1024 * 1024)
    app["bot"] = bot
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    forum.install(app, bm)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("BAZAR слушает порт %s", PORT)
    asyncio.create_task(keepalive())
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
