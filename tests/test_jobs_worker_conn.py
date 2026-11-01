# -*- coding: utf-8 -*-
"""执行方断线不退出：连库断了（DB 重试耗尽）后循环继续，不是整个进程退出。"""
from __future__ import annotations

from open_guji_cv.jobs import runner as R
from open_guji_cv.jobs import store as S


class OperationalError(Exception):
    """模拟 psycopg.OperationalError（类名对得上即可）。"""


def test_work_survives_connection_drops(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "HOME", tmp_path)
    monkeypatch.setattr(S, "who", lambda: "worker-test")
    monkeypatch.setattr(R, "_runner_commit", lambda: None)
    monkeypatch.setattr(R, "_runner_outdated", lambda: False)
    monkeypatch.setattr(R, "_preflight", lambda: None)
    monkeypatch.setattr(R, "_disk_gate", lambda say=print: None)
    monkeypatch.setattr(R, "_last_book", lambda: None)
    monkeypatch.setattr(R.BOARD, "publish", lambda *a, **kw: None)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    drops = {"left": 2}

    def fake_db(fn, *a, **kw):
        if fn is S.reap and drops["left"] > 0:
            drops["left"] -= 1
            raise OperationalError("server closed the connection unexpectedly")
        if fn is S.reap:
            return []
        if fn is S.claim:
            return None          # 队列空
        return None

    monkeypatch.setattr(S, "DB", lambda: fake_db)
    said = []
    assert R.work(until_empty=True, say=said.append) == 0
    assert drops["left"] == 0
    assert any("连库断了" in s for s in said)
