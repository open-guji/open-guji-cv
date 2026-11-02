# -*- coding: utf-8 -*-
"""执行方断线不退出：连库断了（DB 重试耗尽）后循环继续，不是整个进程退出。

测试不改全局 time.sleep：重试等待用 R.CONN_RETRY_S=0；work() 放在线程里跑，超时即失败，不会卡住整个 pytest。
"""
from __future__ import annotations

import threading

from open_guji_cv.jobs import runner as R
from open_guji_cv.jobs import store as S


class OperationalError(Exception):
    """模拟 psycopg.OperationalError（类名对得上即可）。"""


def test_work_survives_connection_drops(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(R, "CONN_RETRY_S", 0)
    monkeypatch.setattr(S, "who", lambda: "worker-test")
    monkeypatch.setattr(R, "_runner_commit", lambda: None)
    monkeypatch.setattr(R, "_runner_outdated", lambda: False)
    monkeypatch.setattr(R, "_preflight", lambda: None)
    monkeypatch.setattr(R, "_disk_gate", lambda say=print: None)
    monkeypatch.setattr(R, "_last_book", lambda: None)
    monkeypatch.setattr(R.BOARD, "publish", lambda *a, **kw: None)
    drops = {"left": 2}

    def fake_db(fn, *a, **kw):
        if fn is S.reap and drops["left"] > 0:
            drops["left"] -= 1
            raise OperationalError("server closed the connection unexpectedly")
        if fn is S.claim:
            return None          # 队列空
        return None if fn is not S.reap else []

    monkeypatch.setattr(S, "DB", lambda: fake_db)
    said: list[str] = []
    result: dict = {}

    def run():
        result["rc"] = R.work(until_empty=True, say=said.append)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=60)
    assert not t.is_alive(), "work() 卡住没有返回"
    assert result.get("rc") == 0
    assert drops["left"] == 0
    assert any("连库断了" in s for s in said)
