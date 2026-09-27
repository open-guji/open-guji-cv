# -*- coding: utf-8 -*-
"""not_a_char / damaged → 排除名单（`crop_exclude` 消费者）；seg_defect **不进**。

2026-09-05 补的缺口：此前这些事件只落金标，没人写进 `crop_exclusions.jsonl`——
「标了缺陷」与「以后别再用这块图」之间是断的。

2026-09-20 用户定：名单只收「不是字」与「原刻残」。切坏/带残留（seg_defect）是真字，
图块能不能进库交给 Step7 准入闸——bxgb 名单 131 条 seg_defect 全是真字，被 9.1 当非字
吃掉；放出 127 条后闸自动放行 95 条与整理本全一致、挡下 32 条送人审。
"""

from __future__ import annotations

import json

import pytest

from open_guji_cv.feedback.consumers import crop_exclude
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.routes import RouteTable


def _ev(key: str, kind: str, payload: dict, seq: int = 1):
    return make_event("b", seq, kind,
                      EventTarget(step="seed_admit", unit="cell", key=key,
                                  book="vol01", page=40, col=9, slot=17),
                      payload, source_format="server")


def _pairs(*evs):
    return [(e, None) for e in evs]


@pytest.fixture()
def lst(tmp_path):
    return tmp_path / "crop_exclusions.jsonl"


def test_seg_defect_is_not_excluded_anymore(lst):
    """切坏/带残留是真字：不进名单，交给准入闸（2026-09-20 用户定）。"""
    res = crop_exclude(_pairs(_ev("vol01:40:9:17", "confirm",
                                  {"v": "seg_defect", "quality": "contaminated", "shape": "蠹"}),
                              _ev("vol01:40:9:18", "confirm",
                                  {"v": "seg_defect", "quality": "truncated"}, seq=2)),
                       list_path=str(lst))
    assert res.added == 0 and res.skipped == 2
    assert not lst.exists()


def test_not_a_char_excluded_with_human_origin(lst):
    res = crop_exclude(_pairs(_ev("vol01:5:1:21", "not_a_char", {})), list_path=str(lst))
    assert res.added == 1
    r = json.loads(lst.read_text(encoding="utf-8").strip())
    assert r["instance_id"] == "vol01:5:1:21"
    assert r["origin"] == "human"          # 人眼实锤那一档，与 gate/pipeline-suspect 分开
    assert r["reason"] == "not_a_char" and r["evidence"] == ["not_text"]


def test_damaged_excluded_with_guess(lst):
    res = crop_exclude(_pairs(_ev("vol01:27:8:6", "confirm", {"v": "damaged", "guess": "塊"})),
                       list_path=str(lst))
    assert res.added == 1
    r = json.loads(lst.read_text(encoding="utf-8").strip())
    assert r["reason"] == "damaged" and "guess=塊" in r["evidence"]


def test_plain_confirm_is_skipped_not_excluded(lst):
    """定字裁决与切分缺陷是两件事——普通 confirm 绝不能进排除名单。"""
    res = crop_exclude(_pairs(_ev("vol01:4:1:3", "confirm",
                                  {"v": "confirm", "shape": "復", "reading": "復"})),
                       list_path=str(lst))
    assert res.added == 0 and res.skipped == 1
    assert not lst.exists()


def test_idempotent_on_rerun(lst):
    e = _ev("vol01:5:1:21", "not_a_char", {})
    assert crop_exclude(_pairs(e), list_path=str(lst)).added == 1
    again = crop_exclude(_pairs(e), list_path=str(lst))
    assert again.added == 0 and again.skipped == 1
    assert len(lst.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_dry_run_writes_nothing(lst):
    res = crop_exclude(_pairs(_ev("vol01:5:1:21", "not_a_char", {})),
                       list_path=str(lst), dry_run=True)
    assert res.added == 1 and not lst.exists()


def test_routes_still_send_seg_defect_and_not_a_char_to_crop_exclude():
    """路由表不改（同一条 kind 规则），seg_defect 到了消费者这里被按 v 过滤掉。"""
    t = RouteTable.load(None)
    seg = _ev("vol01:40:9:17", "confirm", {"v": "seg_defect", "quality": "truncated"})
    nac = _ev("vol01:5:1:21", "not_a_char", {})
    ok = _ev("vol01:4:1:3", "confirm", {"v": "confirm", "shape": "復"})
    for e in (seg, nac):
        assert "crop_exclude" in {d.consumer for d in t.destinations(e)}
    assert crop_exclude(_pairs(ok)).added == 0
    assert crop_exclude(_pairs(seg)).added == 0


def test_confirm_and_not_a_char_invalidate_seed_admit():
    """人裁落定 → 这一页 seed_admit 显式失效（2026-09-20 用户报「裁完再载入卡还在」：
    裁决进了库、产物不知道，控制台待审列表读的是产物）。"""
    t = RouteTable.load(None)
    for e in (_ev("vol01:4:1:3", "confirm", {"v": "confirm", "shape": "復"}),
              _ev("vol01:5:1:21", "not_a_char", {})):
        inv = [d for d in t.destinations(e) if d.consumer == "product_invalidate"]
        assert inv and inv[0].extra.get("step") == "seed_admit"
