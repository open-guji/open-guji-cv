# -*- coding: utf-8 -*-
"""seg_defect / not_a_char → 排除名单（`crop_exclude` 消费者）。

2026-09-05 补的缺口：此前这些事件只落金标，没人写进 `crop_exclusions.jsonl`——
「标了缺陷」与「以后别再用这块图」之间是断的。
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


def test_seg_defect_appends_with_human_origin(lst):
    res = crop_exclude(_pairs(_ev("vol01:40:9:17", "confirm",
                                  {"v": "seg_defect", "quality": "contaminated", "shape": "蠹"})),
                       list_path=str(lst))
    assert res.added == 1
    r = json.loads(lst.read_text(encoding="utf-8").strip())
    assert r["instance_id"] == "vol01:40:9:17"
    assert r["origin"] == "human"          # 人眼实锤那一档，与 gate/pipeline-suspect 分开
    assert r["reason"] == "seg_defect"
    assert "contaminated" in r["evidence"] and "shape=蠹" in r["evidence"]


def test_not_a_char_also_excluded(lst):
    res = crop_exclude(_pairs(_ev("vol01:5:1:21", "not_a_char", {})), list_path=str(lst))
    assert res.added == 1
    assert json.loads(lst.read_text(encoding="utf-8").strip())["evidence"] == ["not_text"]


def test_plain_confirm_is_skipped_not_excluded(lst):
    """定字裁决与切分缺陷是两件事——普通 confirm 绝不能进排除名单。"""
    res = crop_exclude(_pairs(_ev("vol01:4:1:3", "confirm",
                                  {"v": "confirm", "shape": "復", "reading": "復"})),
                       list_path=str(lst))
    assert res.added == 0 and res.skipped == 1
    assert not lst.exists()


def test_idempotent_on_rerun(lst):
    e = _ev("vol01:40:9:17", "confirm", {"v": "seg_defect", "quality": "truncated"})
    assert crop_exclude(_pairs(e), list_path=str(lst)).added == 1
    again = crop_exclude(_pairs(e), list_path=str(lst))
    assert again.added == 0 and again.skipped == 1
    assert len(lst.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_dry_run_writes_nothing(lst):
    res = crop_exclude(_pairs(_ev("vol01:40:9:17", "confirm",
                                  {"v": "seg_defect", "quality": "truncated"})),
                       list_path=str(lst), dry_run=True)
    assert res.added == 1 and not lst.exists()


def test_routes_send_seg_defect_and_not_a_char_to_crop_exclude():
    t = RouteTable.load(None)
    seg = _ev("vol01:40:9:17", "confirm", {"v": "seg_defect", "quality": "truncated"})
    nac = _ev("vol01:5:1:21", "not_a_char", {})
    ok = _ev("vol01:4:1:3", "confirm", {"v": "confirm", "shape": "復"})
    for e in (seg, nac):
        assert "crop_exclude" in {d.consumer for d in t.destinations(e)}
    # 普通 confirm 也路由给 crop_exclude（同一条 kind 规则），由消费者自己按 v 过滤
    assert crop_exclude(_pairs(ok)).added == 0
