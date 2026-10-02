# -*- coding: utf-8 -*-
"""下版框候选模型：关着不改产物、候选信号、硬护栏、模型读写、弃权不改线。自造数据，不依赖仓外。"""
import numpy as np
import pytest

from open_guji_cv.bottompeak_model import signals as S
from open_guji_cv.bottompeak_model.chooser import choose, select
from open_guji_cv.bottompeak_model.model import GUARD_DEFAULTS
from open_guji_cv.steps.border_detect import BorderDetectParams
from open_guji_cv.utils.peak_line_search import find_horizontal_border, find_vertical_lines


def _page(h=1400, w=1000, bar_y=1200):
    m = np.zeros((h, w))
    xs = [100 + i * 100 for i in range(9)]
    for x in xs:
        m[200:bar_y, x:x + 3] = 1                       # 界行
    m[bar_y:bar_y + 10, 100:900] = 1                     # 下版框粗条
    m[bar_y + 30:bar_y + 34, 100:900] = 1                # 外框细线
    for r in range(260, bar_y - 40, 120):                # 文字块
        for x in xs[:-1]:
            m[r:r + 70, x + 20:x + 80] = 1
    return m


def test_params_off_dump_unchanged():
    d = BorderDetectParams().model_dump(mode="json")
    assert not any(k.startswith("bottom_peak_model") for k in d)
    on = BorderDetectParams(bottom_peak_model=True).model_dump(mode="json")
    assert on["bottom_peak_model"] is True and on["bottom_peak_model_fingerprint"]


def test_identity_chooser_is_bytewise_same():
    m = _page()
    vl = find_vertical_lines(m, expected_count=10)
    base = find_horizontal_border(m, "bottom", verticals=vl, book_gap=200.0)
    same = find_horizontal_border(m, "bottom", verticals=vl, book_gap=200.0,
                                  bottom_chooser=lambda mask, cur, v, g, lo, hi: cur)
    assert base == same


def test_enumerate_candidates_has_rule_and_finite_features():
    m = _page()
    vl = find_vertical_lines(m, expected_count=10)
    rec = {}

    def spy(mask, cur, v, g, lo, hi):
        rec["c"] = S.enumerate_candidates(mask, cur, v, g, lo, hi, top_pos=200.0)
        return cur
    find_horizontal_border(m, "bottom", verticals=vl, book_gap=200.0, bottom_chooser=spy)
    cands = rec["c"]
    assert cands and sum(c["feats"]["is_rule"] for c in cands) == 1
    for c in cands:
        assert set(S.FEATURES) <= set(c["feats"])
        assert all(np.isfinite(v) for v in c["feats"].values())


def test_select_guardrails():
    g = dict(GUARD_DEFAULTS)
    finals = [1000.0, 1010.0, 990.0, 1100.0]          # 0=现役
    # 模型最爱靠上 10px 的（k=2）→ 护栏不许往上，退而选 k=1
    assert select(finals, 0, [0.2, 0.6, 0.9, 0.5], g) == 1
    # 最爱的在 +100 外（>down_max）→ 不采信
    assert select(finals, 0, [0.2, 0.1, 0.1, 0.99], g) == 0
    # 没比现役高出 margin → 保持
    assert select(finals, 0, [0.5, 0.55, 0.1, 0.1], g) == 0
    # 概率低于 min_prob → 保持
    assert select(finals, 0, [0.0, 0.2, 0.0, 0.0], g) == 0


class _Const:
    guard = dict(GUARD_DEFAULTS)

    def __init__(self, fn):
        self.fn = fn

    def probs(self, cands):
        return np.array([self.fn(c) for c in cands])


def test_choose_switches_and_abstains():
    m = _page()
    vl = find_vertical_lines(m, expected_count=10)
    holder = {}

    def spy(mask, cur, v, g, lo, hi):
        holder["a"] = (mask, cur, v, g, lo, hi)
        return cur
    find_horizontal_border(m, "bottom", verticals=vl, book_gap=200.0, bottom_chooser=spy)
    mask, cur, v, g, lo, hi = holder["a"]
    # 模型对全部候选等概率 → 保持
    line, ev = choose(_Const(lambda c: 0.5), mask, cur, v, g, lo, hi, 200.0)
    assert line is cur and ev["reason"] == "kept"
    # 模型异常 → 弃权，原样返回
    def boom(c):
        raise RuntimeError("x")
    line, ev = choose(_Const(boom), mask, cur, v, g, lo, hi, 200.0)
    assert line is cur and ev["reason"].startswith("abstain:error")


def test_model_roundtrip(tmp_path):
    pytest.importorskip("sklearn")
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from open_guji_cv.bottompeak_model.model import file_fingerprint, load_model, save_model
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(60, len(S.FEATURES))), columns=list(S.FEATURES))
    clf = LogisticRegression().fit(X, (X.iloc[:, 0] > 0).astype(int))
    p = tmp_path / "m.joblib"
    fp = save_model(p, clf, list(S.FEATURES), None, {"model_id": "t"})
    mod = load_model(p)
    assert mod.fingerprint == fp == file_fingerprint(p) and mod.features == list(S.FEATURES)
    assert mod.guard == GUARD_DEFAULTS
