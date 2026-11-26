# -*- coding: utf-8 -*-
"""规则 A 少刻例支 `rare_ref_sparse`（A23 L02 深挖，sheldon 11-06 同意，缺省关）。全部自造数据。

整理本字在本书库里刻例 ≤2、5-b 首位是它（或罕用码位整理本字的异体）、领先同来源组外最好候选 ≥ 阈值 → 放行整理本字。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.engine import params_hash
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams, rare_sparse_decide

from test_seed_admit_rare_ref import _run

VAR = {frozenset("𮪍騎")}
av = lambda a, b: frozenset((a, b)) in VAR   # noqa: E731
BASE = dict(n_lib=0, doubts=["库 unsure(cov=0.914)"], guard=None, verdict="unsure", lib_char=None, lib_top="蜀",
            max_n=2, lead_min=0.02, variant=True, are_variants=av)


def _d(ref, cands, **k):
    return rare_sparse_decide(ref=ref, cands=cands, **{**BASE, **k})


def test_decide_basic():
    c = [("奴", 0.979, "emb"), ("姒", 0.933, "emb"), ("奻", 0.92, "emb")]
    assert _d("奴", c) == ("奴", 0.046)
    assert _d("奴", c, n_lib=3) is None                         # 库里已有 3 例：归库匹配
    assert _d("奴", c, lead_min=0.05) is None                   # 领先不够
    assert _d("叙", c) is None                                  # 5-b 首位不是整理本字（参校本可能错）
    assert _d("奴", [("奴", 0.979, "emb")]) is None              # 没有同来源对手
    assert _d("奴", [("奴", 0.979, "emb"), ("姒", 0.5, "cnn")]) is None   # 分数不跨来源比
    assert _d("奴", c, doubts=["near_form"]) is None             # 硬疑问照拦
    assert _d("奴", c, guard="conflict") is None
    assert _d("奴", c, verdict="same", lib_char="叙") is None    # 库明确认成别的字
    assert _d("奴", c, group_chars=frozenset("奴")) is None      # 字组里的字归字组流程
    assert _d("己", [("己", 0.99, "emb"), ("乙", 0.9, "emb")]) is None   # 己已巳不碰
    assert _d("〓", c) is None and _d(None, c) is None


def test_decide_variant_rare_codepoint():
    """罕用码位整理本字（扩展 B 以上），5-b 首位是它的异体（字体里只有通行字）：算整理本字一组。"""
    c = [("騎", 0.970, "emb"), ("驥", 0.918, "emb"), ("𮪍", 0.945, "emb")]
    assert _d("𮪍", c) == ("𮪍", 0.052)                          # 组内的 𮪍 不当对手
    assert _d("𮪍", c, variant=False) is None
    # 常用字不走异体：首位是异体也不放
    assert rare_sparse_decide(ref="騎", cands=[("𮪍", 0.97, "emb"), ("驥", 0.9, "emb")], **BASE) is None


def test_default_off_not_in_hash():
    assert SeedAdmitParams().rare_ref_sparse is False
    assert params_hash(SeedAdmitParams()) == params_hash(SeedAdmitParams(rare_ref_sparse_lead=0.05))
    assert params_hash(SeedAdmitParams()) != params_hash(SeedAdmitParams(rare_ref_sparse=True))


@pytest.mark.usefixtures("seed_admit_switches_off")   # 放行开关缺省全关，只看这一支，见 conftest
def test_pass_coord_unanchored_low_cov(tmp_path, monkeypatch):
    """规则 A 两支都放不了的格：坐标对位、整页没锚、库首位 cov < 0.90。开了这支才放。"""
    monkeypatch.setattr(sa, "_keben_counts", lambda _p: {})
    kw = dict(rare=["奴", "姒", "奻"], cands=(("努", 0.88),), align=None, coord="奴")
    off = _run(tmp_path / "a", monkeypatch, params={"patch_missing": "skip"}, **kw)
    assert not off.admit
    on = _run(tmp_path / "b", monkeypatch, params={"rare_ref_sparse": True, "rare_ref_sparse_lead": 0.005, "patch_missing": "skip"}, **kw)
    assert on.admit and on.char == "奴" and on.channel == "rare_ref"
    assert on.evidence["rare_ref"]["via"] == "sparse_coord" and on.evidence["rare_ref"]["n_lib"] == 0
    monkeypatch.setattr(sa, "_keben_counts", lambda _p: {"奴": 5})
    many = _run(tmp_path / "c", monkeypatch, params={"rare_ref_sparse": True, "rare_ref_sparse_lead": 0.005, "patch_missing": "skip"}, **kw)
    assert not many.admit


def test_pass_respects_keep_ref_review(monkeypatch):
    """护栏拿整理本字拦下的格（ctx_guard_ref 等）不放回，同规则 A 的 lane_keep_ref_review。"""
    from types import SimpleNamespace as NS
    rec = NS(id="x:1:1:1", admit=False, provenance=None, channel=None, doubts=["ctx_guard_ref"], evidence={}, char="叙")
    m = NS(verdict="unsure", char=None, candidates=[("努", .88)], guard=None, cov=.88)
    rare = NS(columns=[NS(chars=[NS(id=rec.id, candidates=[NS(char="奴", score=.9, font="emb"), NS(char="姒", score=.85, font="emb")])])])
    out = [NS(chars=[rec])]
    p = sa.SeedAdmitParams(rare_ref_sparse=True)
    assert sa._rare_ref_sparse_pass(p, out, {rec.id: m}, {}, rare, {rec.id: "奴"}, {}) == 0
    rec.doubts = []
    assert sa._rare_ref_sparse_pass(p, out, {rec.id: m}, {}, rare, {rec.id: "奴"}, {}) == 1 and rec.char == "奴"
