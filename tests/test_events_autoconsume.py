# -*- coding: utf-8 -*-
"""POST /api/events 写完就消费（`EventsIn.consume`）。

用户 2026-09-05：「审查完了就自动消费吧，有必要再点一次吗」。批次是台账不是闸，
事件既然落盘了，再要人去「收割与消费」点一次只是重复动作——组视图按组分批，
一轮十几个批次就得点十几次。
"""

from __future__ import annotations

import pytest

# 直接调端点函数，不起 TestClient——那需要 httpx，不值得为一个测试加依赖。


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把事件/批次/金标都指到 tmp，别碰真数据。

    控制台重构 C1/C3 之后，这三个 Store 不再是 `console/app.py` 的模块级单例了：
    根目录在 `console/deps.py`（那里同时是 CLI 与云端道的注入口），路由在
    `console/routers/feedback.py`。改根的做法也跟着换成**改 deps 的根 ＋ 清缓存的单例**，
    比 setattr 三个模块级名字更贴近真实用法（`deps.set_roots()` 走的是同一条路）。
    两处都用 monkeypatch，teardown 自动还原，不会漏给下一个测试。
    """
    from open_guji_cv.console import deps
    from open_guji_cv.console.routers import feedback as mod

    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)   # 下次取时按新根重建
    return mod


def _post(client, events, **kw):
    body = {"batch": "t-batch", "step": "admit_decide", "unit": "cell",
            "kind": "confirm", "events": events, **kw}
    return client.api_events(client.EventsIn(**body))


def test_consume_runs_by_default(client):
    d = _post(client, [{"id": "vol01:4:1:3", "v": "seg_defect", "quality": "truncated"}])
    assert d["appended"] == 1
    # 落库结果一并回给前端（哪个消费者收了几条）
    assert "consumed" in d
    got = {x["consumer"]: x for x in d["consumed"]}
    assert "gold_add" in got and got["gold_add"]["added"] == 1


def test_consume_can_be_turned_off(client):
    d = _post(client, [{"id": "vol01:4:1:3", "v": "seg_defect", "quality": "truncated"}],
              consume=False)
    assert d["appended"] == 1 and "consumed" not in d


def test_second_post_is_idempotent(client):
    ev = [{"id": "vol01:4:1:3", "v": "seg_defect", "quality": "truncated"}]
    _post(client, ev)
    d = _post(client, ev)          # 同一条再来一次
    got = {x["consumer"]: x for x in d.get("consumed", [])}
    # 事件是新的一条（seq 续号），但金标按 id 合并 → 内容相同不算「新增」
    assert got.get("gold_add", {}).get("added", 0) == 0


def test_empty_events_do_not_trigger_consume(client):
    d = _post(client, [{"no_id": 1}])
    assert d["appended"] == 0 and "consumed" not in d


def test_consume_failure_does_not_break_the_write(client, monkeypatch):
    """消费炸了也得把「事件已保存」如实告诉前端——否则人以为裁决丢了。"""
    from open_guji_cv.console.routers import feedback as mod

    def boom(*a, **kw):
        raise RuntimeError("路由表坏了")

    monkeypatch.setattr(mod, "route_and_consume", boom)
    d = _post(client, [{"id": "vol01:4:1:3", "v": "seg_defect", "quality": "truncated"}])
    assert d["appended"] == 1
    assert "路由表坏了" in d["consume_error"]
