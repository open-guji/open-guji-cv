# -*- coding: utf-8 -*-
"""库高置信兜底通道 `lib_confident` 已随 W2（GUJI-49）删除；这里只留「库判 unsure、Step6 退回先验」的格
**仍落审**这条回归（`lib_confident_cov/gap` 字段不存在了，旧 yaml 里写了也被忽略，十册 yaml 零使用）。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
import pytest
from helpers import (make_book, make_ctx, page_align_ref, page_decision,
                     page_match, write_product)
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _confusable_char

pytestmark = pytest.mark.usefixtures("no_cnn")   # CNN 通道开不开随环境变，钉成关（overview#407）

BOOK, PAGE, COL, SLOT = "tbook", 1, 1, 15
TOP, SECOND = "耶", "則"          # 实例取自 vol04:154:3:19（Z10 点名的放宽候选）


def _run(tmp_path, monkeypatch, *, cands, verdict="unsure", guard=None,
         source="prior", align=None, params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, verdict=verdict, cov=cands[0][1], wmax=16.0,
                 guard=guard, candidates=cands),
        ]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[
            dict(slot=SLOT, char=None, margin=0.12, source=source),
        ]))
    if align is not None:
        write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
            PAGE, BOOK, col=COL, recs=[dict(slot=SLOT, **align)]))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


HIGH = [(TOP, 0.993), (SECOND, 0.937)]


def test_fixture_chars_are_not_confusable():
    """夹具前提：耶／則 不在任何形近表里——否则下面的「放行」用例测的是别的东西。"""
    assert not _confusable_char(TOP)


def test_default_off_is_noop(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=HIGH)
    assert r.admit is False and r.channel is None
    assert any("上下文 margin 不足" in d for d in r.doubts)


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
