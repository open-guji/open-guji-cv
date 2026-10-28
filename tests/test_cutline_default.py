# -*- coding: utf-8 -*-
"""Step7「切分裁决」默认选中 U-Net 与 verdict 口径（overview#188，2026-09-28）。

三层：
- `review/cutline_default.py`：书级开关 `params.review.cutline_default` 与每卡默认项；
- `/api/cutline/cases`：把 `default_idx`／`default_pick`／`cutline_default` 下发给前端；
- 前端 `components/cutline/cutlineVerdict.ts`：落定时 ok/moved 跟默认项比，另记
  `picked_source`／`default_pick`。这层用 node 的 `--experimental-strip-types` 直接跑源码
  （node ≥ 22.6；没有 node 的机器 skip——前端构建本来就要 node，缺的是可选件不是数据）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_guji_cv.gold.atomic import CUTLINE_KEYS
from open_guji_cv.review.cutline_default import (attach_default_pick, cutline_default_mode,
                                                 default_pick)

CANDS = [{"kind": "straight"}, {"kind": "seam_narrow"}, {"kind": "unet_seam"}]


def _book(review: dict | None):
    return SimpleNamespace(params={} if review is None else {"review": review})


# ── 书级开关 ─────────────────────────────────────────────────────────

def test_mode_defaults_to_unet():
    assert cutline_default_mode(_book(None)) == "unet"
    assert cutline_default_mode(_book({})) == "unet"
    assert cutline_default_mode(SimpleNamespace()) == "unet"      # 老 BookSpec 没有 params


def test_mode_reads_book_param():
    assert cutline_default_mode(_book({"cutline_default": "chosen"})) == "chosen"
    assert cutline_default_mode(_book({"cutline_default": "unet"})) == "unet"


def test_mode_rejects_typo():
    with pytest.raises(ValueError, match="cutline_default"):
        cutline_default_mode(_book({"cutline_default": "engine"}))


# ── 每卡默认项 ───────────────────────────────────────────────────────

def test_default_pick_prefers_unet():
    assert default_pick(CANDS, 0, "unet") == (2, "unet")


def test_default_pick_falls_back_to_chosen_without_unet():
    assert default_pick(CANDS[:2], 1, "unet") == (1, "chosen")
    assert default_pick([], None, "unet") == (None, "chosen")


def test_default_pick_chosen_mode_ignores_unet():
    assert default_pick(CANDS, 0, "chosen") == (0, "chosen")


def test_attach_default_pick_in_place():
    cases = [{"candidates": CANDS, "chosen": 0}, {"candidates": [], "chosen": None}]
    attach_default_pick(cases, "unet")
    assert [(c["default_idx"], c["default_pick"]) for c in cases] == [(2, "unet"), (None, "chosen")]


def test_new_event_fields_reach_touching_cuts_gold():
    """来源字段要进金标（`_expected_of` 只留 CUTLINE_KEYS），且与 y/cand 同组整组替换。"""
    from open_guji_cv.feedback.consumers import _expected_of
    from open_guji_cv.feedback.events import EventTarget, make_event
    assert {"picked_source", "default_pick"} <= set(CUTLINE_KEYS)
    e = make_event("b", 1, "cutline",
                   EventTarget(step="row_segment", unit="boundary", key="vol02:3:4:17",
                               book="vol02", page=3, col=4, slot=17),
                   {"y": 10, "y_old": 10, "verdict": "ok", "cand": "unet_seam",
                    "picked_source": "unet", "default_pick": "unet"})
    ex = _expected_of(e)
    assert ex["picked_source"] == "unet" and ex["default_pick"] == "unet"


# ── 接口 ─────────────────────────────────────────────────────────────


# ── 前端口径（node 跑 cutlineVerdict.ts）────────────────────────────


