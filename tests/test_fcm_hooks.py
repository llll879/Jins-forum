# -*- coding: utf-8 -*-
"""Проверка, что звонки отправляют FCM: вызов (ring) и отмена вызова (call_end).  Запуск: python -m unittest tests.test_fcm_hooks"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import test_calls as T  # noqa: E402  (ставит заглушки окружения и импортирует forum_calls)
import forum_fcm  # noqa: E402

C = T.C


class FcmHooks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        C.CALLS.clear(); C.IN_CALL.clear(); C.BOX.clear(); T.ST.__init__()
        self.sent = []
        self._en, self._ring, self._end = forum_fcm.enabled, forum_fcm.call_ring, forum_fcm.call_end
        forum_fcm.enabled = lambda: True
        forum_fcm.call_ring = lambda uid, c, by: self.sent.append(("ring", uid, c["id"], (by or {}).get("name")))
        forum_fcm.call_end = lambda uid, cid: self.sent.append(("end", uid, cid))

    def tearDown(self):
        forum_fcm.enabled, forum_fcm.call_ring, forum_fcm.call_end = self._en, self._ring, self._end

    async def test_ring_and_cancel(self):
        r = await T.call(C.a_start, 1, {"peer": 2})
        cid = r.data["call"]["id"]
        import asyncio
        await asyncio.sleep(0.05)                       # фоновая задача _fcm_ring
        self.assertIn(("ring", 2, cid, "U1"), self.sent)
        await T.call(C.a_leave, 1, {"call": cid})      # звонящий отменил -> вызов гаснет и на закрытом приложении
        self.assertIn(("end", 2, cid), self.sent)

    async def test_decline_clears_other_devices(self):
        r = await T.call(C.a_start, 1, {"peer": 2})
        cid = r.data["call"]["id"]
        await T.call(C.a_decline, 2, {"call": cid})
        self.assertIn(("end", 2, cid), self.sent)


if __name__ == "__main__":
    unittest.main()
