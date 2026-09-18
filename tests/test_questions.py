# -*- coding: utf-8 -*-
"""问题登记表（`feedback/questions.py`）与路由表必须说同一件事。

登记表是给人看的「这个问题落哪个分片」，路由表是机器真正执行的。
两者分头维护就会漂——而漂了不会报错，只会让裁决静默落错分片
（2026-09-18 修的那个 bug 正是如此：70 条 head 的 yes/no 混进了
问「界行在不在缝上」的分片，档位都对不上，谁拿去评测谁中招）。

所以这里逐条把登记表里的 question 造成事件喂给路由表，断言落点一致。
新增裁决台时如果只改了一边，这个测试会红。
"""
from __future__ import annotations

import pytest

from open_guji_cv.feedback.events import Event, EventTarget
from open_guji_cv.feedback.questions import QUESTIONS, BY_ID, validate
from open_guji_cv.feedback.routes import RouteTable


def _event_for(q) -> Event:
    payload: dict = {"question": q.id}
    # `confirm` 这一路靠 payload.v 二次分流（定字 → glyph.db / 切分缺陷 → 金标），
    # 不给 v 的话 gold_add 那一路取不到 expected。
    if q.kind == "confirm":
        payload["v"] = "seg_defect" if q.id.endswith("seg_quality") else "confirm"
    return Event(id="e", ts="t", batch="b", seq=1, actor="user", kind=q.kind,
                 target=EventTarget(step=q.id.split(".")[0], unit=q.unit, key="bxgb:1:1"),
                 payload=payload)


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q.id)
def test_shard_matches_route_table(q):
    """登记表声明的分片，必须是路由表真正会落的那个。"""
    dests = [d.shard for d in RouteTable.load().destinations(_event_for(q))
             if d.consumer == "gold_add"]
    if q.shard is None:
        return          # 不进金标的（定字只进 glyph.db），不约束 gold_add 去向
    assert q.shard in dests, (
        f"{q.id} 登记表说落 {q.shard}，路由表实际落 {dests}")


def test_ids_unique():
    assert len(BY_ID) == len(QUESTIONS), "question id 有重复"


def test_id_shape():
    """`<step>.<对象>.<问什么>`，且中段与 unit 一致。"""
    for q in QUESTIONS:
        parts = q.id.split(".")
        assert len(parts) == 3, f"{q.id} 不是三段式"
        assert parts[1] == q.unit, f"{q.id} 中段 {parts[1]} 与 unit={q.unit} 不符"


def test_answers_are_controlled():
    """有枚举的问题，`validate` 认枚举内的、拒枚举外的。"""
    for q in QUESTIONS:
        if not q.answers:
            continue
        for a in q.answers:
            assert validate(q.id, a), f"{q.id} 应接受 {a}"
        assert not validate(q.id, "__不存在的答案__"), f"{q.id} 不该接受枚举外的值"


def test_unknown_question_rejected():
    assert not validate("no.such.question", "ok")
