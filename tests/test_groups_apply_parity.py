# -*- coding: utf-8 -*-
"""`apply_group_verdicts` 与 `seed_admit` 里现有三处实现的**对拍**（S0 的核心验收，S2 的前提）。

做法：同一批合成记录，深拷贝两份，一份跑旧函数（`_ry_group_pass`／`_rr_clf_pass`／`_ji_yi_si_clf_cell`），
一份走「后端 judge → apply_group_verdicts」，然后逐字段比 `admit／char／channel／provenance／doubts／evidence`。
全部自造数据与桩（桩 `rr_clf.classify`／`_page_patch`），不读真书。

已知且文档化的差别（S2 要解决，不是 bug）：旧的 jys 遍**边走边改**——前一格被改字后，后一格的窗口会变
（`_clf_ctx` 取邻格「已放行字」）。批量 apply 的窗口来自遍前状态。所以 jys 在这里按「单格隔离」对拍；
最后一条测试把这个差别钉出来。PR2 的 `ctx_window`（邻字只取整理本对位字）正是为消除它。
"""
from __future__ import annotations

import copy
import itertools
import json
from types import SimpleNamespace

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.steps.seed_admit as sa
import open_guji_cv.utils.rr_clf as rr
from open_guji_cv.groups import GROUPS, JudgeInput, apply_group_verdicts, window_from_text
from open_guji_cv.groups.backends import JysRuleBackend, RrImageBackend, RyV2TableBackend
from open_guji_cv.utils import ji_yi_si_clf, ry_group
from open_guji_cv.utils.ji_yi_si_clf import ctx_key


def rec(i, *, admit=False, char="", channel=None, provenance="", doubts=(), evidence=None, ref=None, col=1):
    return SimpleNamespace(id=f"t:1:{col}:{i}", col=col, slot=i, sub=None, admit=admit, char=char, channel=channel,
                           provenance=provenance, doubts=list(doubts), evidence=dict(evidence or {}), _ref=ref)


def snap(r):
    return {"admit": r.admit, "char": r.char, "channel": r.channel, "provenance": r.provenance,
            "doubts": list(r.doubts), "evidence": r.evidence}


def amap_of(recs):
    return {r.id: (r._ref, "equal") for r in recs}


def jwin(seq, amap, i):
    """判别窗口：与现行 `_clf_ctx` 同一取法（邻格已放行字，否则整理本字，否则 □），宽 30。"""
    return window_from_text(sa._clf_ctx(seq, amap, i, -1), sa._clf_ctx(seq, amap, i, 1))


# =================================================================== ry：抬待审（只抬、不降、不改字）
def _ry_scenario():
    N = rec(1, admit=True, char="而", channel="dual", ref="而")                # 邻格，已放行
    cells = [
        N,
        rec(2, ref="日"),                                                      # A 表一致且＝整理本 → 抬
        rec(3, ref="日"),                                                      # B 表给「曰」≠整理本 → ry_disagree
        rec(4, ref="曰"),                                                      # C 弃权
        rec(5, ref="日"),                                                      # D haiku 否决
        rec(6, ref="日"),                                                      # E 表里没有这格
        rec(7, admit=True, char="日", channel="dual", ref="日"),                # F 已放行 → 不碰
        rec(8, admit=True, char="日", channel="human", provenance="human", ref="日"),   # G 人裁位
        rec(9, ref="日", doubts=["occluded"]),                                 # H 遮挡
        rec(10, ref="日", doubts=["seal_blank"]),                              # I 印章
        rec(11, ref="日", doubts=["always_review", "near_form"]),              # J 抬时清 always_review
        rec(12, ref="天"),                                                     # K 整理本字不在组内
        rec(13, ref="曰"),                                                     # L 上下文哈希对不上
        rec(14, ref="日", doubts=["excluded"]),                                # M 排除名单：旧遍先剔出序列
    ]
    return cells


def _ry_table(tmp_path, cells):
    seq = [r for r in cells if "excluded" not in r.doubts]
    amap = amap_of(cells)
    votes = lambda m, g, h: {"muse": list(m), "gemini": list(g), "haiku": list(h)}      # noqa: E731
    spec = {2: votes("日日", "日日", "日"), 3: votes("曰曰", "曰曰", "曰"), 4: {"muse": ["日", "不确定"], "gemini": ["日", "日"]},
            5: votes("日日", "日日", "曰"), 11: votes("日日", "日日", "日"), 13: votes("曰曰", "曰曰", "曰")}
    table = {}
    for i, r in enumerate(seq):
        if r.slot not in spec:
            continue
        ctx = ctx_key(sa._clf_ctx(seq, amap, i, -1), sa._clf_ctx(seq, amap, i, 1))
        table[r.id] = {"ctx": "0000" if r.slot == 13 else ctx, "ver": "ry-v2", "votes": spec[r.slot]}
    p = tmp_path / "ry.json"
    p.write_text(json.dumps({"cells": table}), encoding="utf-8")
    ry_group._load.cache_clear()
    return str(p)


def test_apply_equals_ry_group_pass(tmp_path):
    cells = _ry_scenario()
    path = _ry_table(tmp_path, cells)
    amap = amap_of(cells)
    old = copy.deepcopy(cells)
    n_old = sa._ry_group_pass([SimpleNamespace(col=1, chars=old)], amap, path)

    new = copy.deepcopy(cells)
    seq = [r for r in new if "excluded" not in r.doubts]
    be, spec = RyV2TableBackend(path), GROUPS["ry"]
    verdicts = {}
    for i, r in enumerate(seq):
        verdicts[r.id] = be.judge(spec, JudgeInput(r.id, r._ref, jwin(seq, amap, i)))
    # 被排除的格也给个判决，apply 自己必须不碰它
    ex = [r for r in new if "excluded" in r.doubts][0]
    verdicts[ex.id] = be.judge(spec, JudgeInput(ex.id, ex._ref, window_from_text("", "")))
    res = apply_group_verdicts(new, verdicts, spec, refs={r.id: r._ref for r in new})

    assert [snap(r) for r in new] == [snap(r) for r in old]
    assert res.lifted == n_old == 2                       # A、J
    assert res.demoted == 0                               # ry 只抬、不降


# =================================================================== rr：只降级（不改字、不放行）
def _rr_scenario():
    return [
        rec(1, admit=True, char="入", channel="dual"),            # 分类器给「人」≠放行 → 降级
        rec(2, admit=True, char="入", channel="match_ref"),       # 给「入」＝放行 → 不动，只写证据
        rec(3, admit=True, char="人", channel="dual"),            # 弃权（pick=None）→ 只写证据
        rec(4, admit=False, char="入"),                           # 未放行 → 不碰
        rec(5, admit=True, char="八", channel="human", provenance="human"),   # 人裁位
        rec(6, admit=True, char="天", channel="dual"),            # 放行字不在组内
        rec(7, admit=True, char="八", channel="dual", provenance="human"),    # provenance=human
        rec(8, admit=True, char="八", channel="dual", doubts=["near_form"]),  # 给「入」≠放行 → 降级且保留原疑问
    ]


_RR_RESULT = {
    1: {"probs": {"人": 0.7, "入": 0.2, "八": 0.05, "其他": 0.05}, "pick": "人", "gated": False, "p": 0.7},
    2: {"probs": {"人": 0.1, "入": 0.8, "八": 0.05, "其他": 0.05}, "pick": "入", "gated": False, "p": 0.8},
    3: {"probs": None, "pick": None, "gated": True, "p": 0.0},
    4: {"probs": {}, "pick": "人", "gated": False, "p": 0.9},
    5: {"probs": {}, "pick": "人", "gated": False, "p": 0.9},
    6: {"probs": {}, "pick": "人", "gated": False, "p": 0.9},
    7: {"probs": {}, "pick": "人", "gated": False, "p": 0.9},
    8: {"probs": {"人": 0.1, "入": 0.75, "八": 0.1, "其他": 0.05}, "pick": "入", "gated": False, "p": 0.75},
}


def test_apply_equals_rr_clf_pass(monkeypatch):
    monkeypatch.setattr(sa, "_page_patch", lambda src, page, col, slot, sub: np.full((2, 2), slot, np.uint8))
    monkeypatch.setattr(rr, "classify", lambda gray, model, p: dict(_RR_RESULT[int(gray[0, 0])]))
    cells = _rr_scenario()
    old = copy.deepcopy(cells)
    p = SimpleNamespace(rr_clf_model="", rr_clf_p=0.5, patch_missing="raise")
    n_old = sa._rr_clf_pass(None, 1, p, [SimpleNamespace(col=1, chars=old)], {})

    new = copy.deepcopy(cells)
    be, spec = RrImageBackend(p_thr=0.5), GROUPS["rr"]
    verdicts = {r.id: be.judge(spec, JudgeInput(r.id, None, window_from_text("", ""),
                                                patch=lambda s=r.slot: np.full((2, 2), s, np.uint8))) for r in new}
    res = apply_group_verdicts(new, verdicts, spec)

    assert [snap(r) for r in new] == [snap(r) for r in old]
    assert res.demoted == n_old == 2 and res.lifted == 0       # 1 与 8
    assert new[0].evidence["demoted_from"] == {"channel": "dual", "by": "rr_clf"}


# =================================================================== jys：规则路，单格隔离对拍
_CTXS = [("甲", "地"), ("天", "丑"), ("而", "地"), ("天", "地")]        # → 巳 / 己 / 已 / 无规则
_STATES = {
    "pending": dict(admit=False, char="己"),
    "pending_always_review": dict(admit=False, char="己", doubts=["always_review", "ji_yi_si", "near_form"]),
    "dual_admitted": dict(admit=True, char="已", channel="dual", provenance="ocr"),
    "strong_conflict_or_same": dict(admit=True, char="已", channel="match_ref", provenance="lib"),
    "strong_same_as_wu": dict(admit=True, char="巳", channel="iron", provenance="lib"),
    "retired_split_ref": dict(admit=True, char="己", channel="split_ref", provenance="ref"),
}
_P = SimpleNamespace(ji_yi_si_clf_table="", ji_yi_si_clf_llm=False, ji_yi_si_clf_margin=0.2)


@pytest.mark.parametrize("state,ctx", list(itertools.product(_STATES, range(len(_CTXS)))))
def test_apply_equals_ji_yi_si_clf_cell(state, ctx):
    prev_c, next_c = _CTXS[ctx]
    seq = [rec(1, admit=True, char=prev_c, channel="dual", ref=prev_c),
           rec(2, ref="已", **_STATES[state]),
           rec(3, admit=True, char=next_c, channel="dual", ref=next_c)]
    amap = amap_of(seq)
    old = copy.deepcopy(seq)
    da, dr = sa._ji_yi_si_clf_cell(old[1], old, 1, amap, _P)

    new = copy.deepcopy(seq)
    spec = GROUPS["jys"]
    v = JysRuleBackend().judge(spec, JudgeInput(new[1].id, "已", jwin(seq, amap, 1)))
    res = apply_group_verdicts([new[1]], {new[1].id: v}, spec)

    assert snap(new[1]) == snap(old[1])
    assert (res.lifted - res.demoted, res.demoted - res.lifted) == (da, dr)


@pytest.mark.parametrize("kw", [dict(channel="human", admit=True, char="已"), dict(doubts=["occluded"]), dict(doubts=["glyph_timeout"]),
                                dict(doubts=["excluded"]), dict(char="天")])
def test_jys_apply_skips_what_the_caller_skips(kw):
    """旧调用方 `_resolve_ji_yi_si` 在进 cell 函数前就跳过：人裁位、遮挡、超时、排除名单、放行字不在本族。"""
    base = dict(admit=False, char="己")
    base.update(kw)
    r = rec(2, **base)
    before = snap(r)
    spec = GROUPS["jys"]
    v = JysRuleBackend().judge(spec, JudgeInput(r.id, "已", window_from_text("甲", "")))   # 规则会给「巳」
    assert v.char == "巳"
    apply_group_verdicts([r], {r.id: v}, spec)
    assert snap(r) == before


def test_known_difference_sequential_window_dependence():
    """已知差别：旧 jys 遍边走边改，前一格被改字后，后一格的窗口随之变化；批量 apply 的窗口来自遍前状态。
    这正是 PR2 `ctx_window`（邻字只取整理本对位字，键不随放行态漂移）要消除的——S2 的前提，不是本包的 bug。"""
    a = rec(1, admit=False, char="己", ref="己")
    b = rec(2, admit=False, char="己", ref="己")
    seq = [a, b]
    amap = amap_of(seq)
    pre = sa._clf_ctx(seq, amap, 1, -1)              # 前一格未放行 → 用整理本字「己」
    a.admit, a.char = True, "巳"                     # 旧遍把前一格改成了「巳」并放行
    assert sa._clf_ctx(seq, amap, 1, -1) == "巳" != pre
