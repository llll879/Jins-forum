# -*- coding: utf-8 -*-
"""Тесты логики звонков (forum_calls) без aiohttp и без БД: вместо них — заглушки.
Запуск:  python -m unittest tests.test_calls  (из корня проекта)
"""
import asyncio
import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------- заглушки окружения
class FErr(Exception):
    def __init__(self, status, code, msg=""):
        self.status, self.code, self.msg = status, code, msg or code


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status = data, status


class Req:
    def __init__(self, uid, body=None, query=None):
        self.uid, self._body, self.query, self._d = uid, body or {}, query or {}, {}

    async def json(self):
        return self._body

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v


class FakePool:
    def __init__(self, st):
        self.st = st

    async def fetchval(self, sql, *a):
        if "FROM users WHERE user_id" in sql:
            return 1 if a[0] in self.st.users else None
        if "count(*) FROM forum_group_members" in sql:
            return len(self.st.members.get(a[0], ()))
        if "FROM forum_group_members WHERE group_id=$1 AND user_id=$2" in sql:
            return 1 if a[1] in self.st.members.get(a[0], ()) else None
        raise AssertionError("fetchval: " + sql)

    async def fetch(self, sql, *a):
        if "FROM forum_group_members WHERE group_id=$1 AND user_id<>$2" in sql:
            return [{"user_id": u} for u in self.st.members.get(a[0], ()) if u != a[1]]
        if "FROM forum_group_members WHERE group_id=$1 AND user_id=ANY" in sql:
            return [{"user_id": u} for u in a[1] if u in self.st.members.get(a[0], ())]
        raise AssertionError("fetch: " + sql)

    async def execute(self, sql, *a):
        if "INSERT INTO direct_messages" in sql:
            self.st.dm.append(a)
        elif "INSERT INTO forum_group_msgs" in sql:
            self.st.gm.append(a)
        else:
            raise AssertionError("execute: " + sql)


class State:
    def __init__(self):
        self.users = {1, 2, 3, 4, 5}
        self.members = {}
        self.blocks = set()
        self.dm, self.gm = [], []


ST = State()


def install_stubs():
    aio = types.ModuleType("aiohttp")
    aio.web = types.SimpleNamespace(middleware=lambda f: f, HTTPException=Exception)
    sys.modules["aiohttp"] = aio
    F = types.ModuleType("forum")
    F.FErr = FErr
    F.J = lambda d, status=200: Resp(d, status)

    def api(fn):
        async def w(req):
            req["fuid"] = req.uid
            try:
                return await fn(req)
            except FErr as e:
                return Resp({"error": e.code}, e.status)
        return w
    F.api = api

    async def jbody(req):
        return req._body
    F.jbody = jbody
    F.to_int = lambda v, default=0: int(v) if str(v).lstrip("-").isdigit() else default

    async def users_map(ids):
        return {i: {"id": i, "name": "U%d" % i, "username": "u%d" % i, "av": False, "sb": ""} for i in ids}
    F.users_map = users_map
    F.ghost = lambda i: {"id": i, "name": "?", "username": "", "av": False, "sb": ""}
    F.P = lambda: FakePool(ST)

    async def block_state(a, b):
        return ((a, b) in ST.blocks, (b, a) in ST.blocks)

    async def get_prefs(uid):
        return {"tg": False}
    F.get_prefs = get_prefs
    F.bm = types.SimpleNamespace(block_state=block_state, rate_ok=lambda k, s: True, _BOT=None, WEBAPP_URL="")
    sys.modules["forum"] = F

    sup = types.ModuleType("support")
    sup.SUPPORT_ID = 999
    sys.modules["support"] = sup

    G = types.ModuleType("forum_groups")

    async def ctx(me, gid, need="see"):
        if me not in ST.members.get(gid, ()):
            raise FErr(403, "not_member")
        return types.SimpleNamespace(channel=gid == 77, g={"title": "Группа %d" % gid})
    G.ctx = ctx
    sys.modules["forum_groups"] = G


install_stubs()
import forum_calls as C  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def call(fn, uid, body=None, query=None):
    r = await fn(Req(uid, body, query))
    return r


class CallsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        C.CALLS.clear()
        C.IN_CALL.clear()
        C.BOX.clear()
        ST.__init__()
        C.RING_SEC = 45
        C.MAX_PARTS = 8

    def evs(self, uid, t=None):
        return [e for e in C.box(uid).q if t is None or e["t"] == t]

    async def test_dm_flow_invite_and_log(self):
        r = await call(C.a_start, 1, {"peer": 2, "video": False})
        self.assertEqual(r.status, 200)
        cid = r.data["call"]["id"]
        self.assertEqual([x["call"] for x in C.ringing_for(2)], [cid])
        # второй не может звонить тому, кто в звонке/звонит ему же — а занятому — «занято»
        r = await call(C.a_join, 2, {"call": cid, "video": True})
        self.assertEqual(r.data["peers"], [1])
        self.assertEqual(len(self.evs(1, "joined")), 1)
        self.assertEqual(C.ringing_for(2), [])
        # сигнализация
        r = await call(C.a_sig, 2, {"call": cid, "to": 1, "items": [{"type": "offer", "sdp": "x"}, {"type": "ice", "c": {}}]})
        self.assertTrue(r.data["ok"])
        self.assertEqual([e["data"]["type"] for e in self.evs(1, "sig")], ["offer", "ice"])
        # посторонний слать сигналы в звонок не может
        r = await call(C.a_sig, 3, {"call": cid, "to": 1, "data": {"type": "offer"}})
        self.assertFalse(r.data["ok"])
        # добавляем третьего
        r = await call(C.a_invite, 1, {"call": cid, "user_ids": [3, 1, 2, 3]})
        self.assertEqual(r.data["invited"], [3])
        self.assertEqual([x["call"] for x in C.ringing_for(3)], [cid])
        self.assertEqual(len(self.evs(2, "invited")), 1)
        r = await call(C.a_join, 3, {"call": cid})
        self.assertEqual(sorted(r.data["peers"]), [1, 2])
        # состояние
        await call(C.a_state, 2, {"call": cid, "muted": True})
        st = [e for e in self.evs(3, "state")][-1]
        self.assertTrue(st["muted"])
        # второй вышел: звонок идёт (1 и 3), потом ушёл первый -> остался один -> личный звонок закрывается
        await call(C.a_leave, 2, {"call": cid})
        self.assertIn(cid, C.CALLS)
        await call(C.a_leave, 1, {"call": cid})
        self.assertNotIn(cid, C.CALLS)
        self.assertEqual(self.evs(3, "end")[0]["reason"], "hangup")
        self.assertEqual(C.IN_CALL, {})
        self.assertEqual(len(ST.dm), 1)
        self.assertTrue(ST.dm[0][2].startswith("📞 Звонок · 0:0"))
        self.assertEqual(ST.dm[0][:2], (1, 2))

    async def test_decline_cancel_timeout_logs(self):
        r = await call(C.a_start, 1, {"peer": 2})
        await call(C.a_decline, 2, {"call": r.data["call"]["id"]})
        self.assertEqual(C.CALLS, {})
        self.assertIn("отклонён", ST.dm[-1][2])
        self.assertEqual(self.evs(1, "end")[-1]["reason"], "declined")
        r = await call(C.a_start, 1, {"peer": 2, "video": True})
        await call(C.a_leave, 1, {"call": r.data["call"]["id"]})
        self.assertEqual(C.CALLS, {})
        self.assertIn("Отменённый", ST.dm[-1][2])
        self.assertEqual(C.ringing_for(2), [])
        r = await call(C.a_start, 1, {"peer": 2})
        C.RING_SEC = -1
        C.box(1)
        await C.sweep()
        self.assertEqual(C.CALLS, {})
        self.assertIn("Пропущенный", ST.dm[-1][2])
        self.assertEqual(self.evs(1, "end")[-1]["reason"], "timeout")

    async def test_busy_blocked_support_and_selfcall(self):
        r = await call(C.a_start, 1, {"peer": 2})
        r2 = await call(C.a_start, 3, {"peer": 1})
        self.assertEqual((r2.status, r2.data["error"]), (409, "busy"))
        r2 = await call(C.a_start, 1, {"peer": 3})
        self.assertEqual(r2.data["error"], "in_call")
        ST.blocks.add((4, 5))
        r2 = await call(C.a_start, 5, {"peer": 4})
        self.assertEqual(r2.data["error"], "blocked")
        r2 = await call(C.a_start, 5, {"peer": 999})
        self.assertEqual(r2.data["error"], "bad_peer")
        r2 = await call(C.a_start, 5, {"peer": 5})
        self.assertEqual(r2.data["error"], "bad_peer")
        r2 = await call(C.a_join, 3, {"call": r.data["call"]["id"]})
        self.assertEqual(r2.status, 403)

    async def test_group_call(self):
        ST.members[10] = {1, 2, 3}
        C.box(2)
        r = await call(C.a_start, 1, {"group": 10, "video": True})
        cid = r.data["call"]["id"]
        self.assertEqual(r.data["call"]["kind"], "group")
        self.assertEqual({x["call"] for x in C.ringing_for(2)} | {x["call"] for x in C.ringing_for(3)}, {cid})
        self.assertEqual(self.evs(2, "gcall")[-1]["call"], cid)
        a = await call(C.a_active, 3, query={"group": 10})
        self.assertEqual(a.data["call"]["n"], 1)
        # не участник не может ни стартовать, ни смотреть
        self.assertEqual((await call(C.a_start, 4, {"group": 10})).status, 403)
        self.assertEqual((await call(C.a_active, 4, query={"group": 10})).status, 403)
        # второй участник группы, нажав «позвонить», попадает в тот же звонок
        r = await call(C.a_start, 2, {"group": 10})
        self.assertEqual(r.data["call"]["id"], cid)
        self.assertEqual(r.data["peers"], [1])
        # 3-й присоединяется через join (звонок ему не обязателен), 4-й — не из группы, но приглашён
        await call(C.a_join, 3, {"call": cid})
        self.assertEqual((await call(C.a_join, 4, {"call": cid})).status, 403)
        await call(C.a_invite, 1, {"call": cid, "user_ids": [4]})
        self.assertEqual((await call(C.a_join, 4, {"call": cid})).status, 200)
        # группа остаётся звонком, пока кто-то есть; запись в чат — по окончании
        C.CALLS[cid]["answered"] = time.time() - 125
        for u in (1, 2, 3):
            await call(C.a_leave, u, {"call": cid})
            self.assertIn(cid, C.CALLS)
        await call(C.a_leave, 4, {"call": cid})
        self.assertNotIn(cid, C.CALLS)
        self.assertEqual(len(ST.gm), 1)
        self.assertIn("Групповой видеозвонок · 2:05", ST.gm[0][2])
        self.assertEqual(self.evs(2, "gcall")[-1]["call"], None)

    async def test_channel_has_no_calls_and_limit(self):
        ST.members[77] = {1}
        self.assertEqual((await call(C.a_start, 1, {"group": 77})).data["error"], "channel")
        C.MAX_PARTS = 2
        r = await call(C.a_start, 1, {"peer": 2})
        cid = r.data["call"]["id"]
        await call(C.a_join, 2, {"call": cid})
        r = await call(C.a_invite, 1, {"call": cid, "user_ids": [3, 4]})
        self.assertEqual((r.data["invited"], r.data["full"]), ([], [3, 4]))

    async def test_stale_participant_dropped_and_rejoin(self):
        r = await call(C.a_start, 1, {"peer": 2})
        cid = r.data["call"]["id"]
        await call(C.a_join, 2, {"call": cid})
        C.box(1).seen -= 100            # у первого пропал интернет
        C.box(2).seen = time.monotonic()
        await C.sweep()
        self.assertEqual(self.evs(2, "left")[-1]["reason"], "lost")
        self.assertNotIn(cid, C.CALLS)  # личный звонок закрылся, второй получил end
        # перезаход в тот же звонок (перезагрузили страницу)
        r = await call(C.a_start, 1, {"peer": 2})
        cid = r.data["call"]["id"]
        await call(C.a_join, 2, {"call": cid})
        r = await call(C.a_join, 2, {"call": cid})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.evs(1, "left")[-1]["reason"], "rejoin")
        self.assertEqual(sorted(C.CALLS[cid]["parts"]), [1, 2])

    async def test_poll_first_and_events(self):
        r = await call(C.a_start, 1, {"peer": 2})
        p = await call(C.a_poll, 2, query={"after": "-1"})
        self.assertEqual(p.data["events"], [])
        self.assertEqual(len(p.data["ringing"]), 1)
        self.assertEqual(p.data["ringing"][0]["by"]["id"], 1)
        seq = p.data["seq"]
        await call(C.a_join, 2, {"call": r.data["call"]["id"]})
        p = await asyncio.wait_for(call(C.a_poll, 1, query={"after": "0"}), 3)
        self.assertTrue(any(e["t"] == "joined" for e in p.data["events"]))
        self.assertEqual(p.data["mine"], r.data["call"]["id"])
        self.assertGreaterEqual(p.data["seq"], seq - 99)

    async def test_ice_servers(self):
        os.environ.pop("CALL_TURN_URLS", None)
        self.assertEqual(len(C.ice_servers(1)), 2)
        os.environ["CALL_TURN_URLS"] = "turn:t.example:3478"
        os.environ["CALL_TURN_SECRET"] = "s"
        ice = C.ice_servers(5)
        self.assertEqual(ice[1]["urls"], ["turn:t.example:3478"])
        self.assertTrue(ice[1]["username"].endswith(":5") and ice[1]["credential"])
        os.environ.pop("CALL_TURN_URLS"), os.environ.pop("CALL_TURN_SECRET")


if __name__ == "__main__":
    unittest.main()
