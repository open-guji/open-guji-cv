# -*- coding: utf-8 -*-
"""IDS 路的整字岭回归判法（`groups/ids_whole`，呂吕、徵徴，2026-10-20）：自造字块，不读真书。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.groups import ids_online as O
from open_guji_cv.groups import ids_whole as W
from open_guji_cv.groups.registry import GROUPS

SPEC = O.IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.3, min_class=4, whole="pix", lam=1.0, size=32)


def _glyph(link: bool, k: int = 0) -> np.ndarray:
    """上下两个口；`link` 为真时中间有一竖连起来（呂），否则留空隙（吕）。k 微移位置当抖动。"""
    g = np.full((90, 80), 255, np.uint8)
    for y0, y1 in ((10, 40), (50, 80)):
        g[y0 + k:y1 + k, 20:60] = 0
        g[y0 + 4 + k:y1 - 4 + k, 26:54] = 255
    if link:
        g[40 + k:50 + k, 36:44] = 0
    return g


def _cells(n=8):
    return ([("呂", _glyph(True, k % 3 - 1), f"vol{k % 4 + 1:02d}", f"c{k}") for k in range(n)]
            + [("吕", _glyph(False, k % 3 - 1), f"vol{k % 4 + 1:02d}", f"d{k}") for k in range(n)])


def _bank(n=8):
    return W.build("lv", _cells(n), 32)


def test_norm_blank_and_shape():
    assert W.norm(np.full((50, 50), 255, np.uint8), 32) is None
    x = W.norm(_glyph(True), 32)
    assert x.shape == (32, 32) and 0.0 <= x.min() and x.max() <= 1.0 and x.max() > 0.9


def test_judge_whole_classifies_and_abstains():
    d = _bank()
    bank = {k: [O._dec(s, 32) for s in v] for k, v in d["templates"].items()}
    members = GROUPS["lv"].members
    v = O.judge_with("lv", _glyph(True), bank, SPEC)
    assert v.char == "呂" and v.why == "agree" and v.extra["form"] == "呂" and v.extra["margin"] >= 0.3
    assert O.judge_with("lv", _glyph(False), bank, SPEC).char == "吕"
    assert set(bank) <= members
    assert O.judge_with("lv", np.full((60, 60), 255, np.uint8), bank, SPEC).why == "abstain:blank"
    # 门槛高到谁也过不了 → 低 margin 弃权，不给字
    hi = O.IdsSpec(**{**SPEC.__dict__, "min_margin": 50.0})
    v = O.judge_with("lv", _glyph(True), bank, hi)
    assert v.char is None and v.why == "abstain:low_margin"
    # 一类模板不够 min_class → 判成它也弃权
    few = {"呂": bank["呂"], "吕": bank["吕"][:2]}
    v = O.judge_with("lv", _glyph(False), few, SPEC)
    assert v.char is None and v.why == "abstain:few_templates"


def test_one_class_bank_abstains():
    d = W.build("lv", [c for c in _cells() if c[0] == "呂"], 32)
    bank = {k: [O._dec(s, 32) for s in v] for k, v in d["templates"].items()}
    assert W.score(_glyph(True), bank, "pix", (0, 1, 0, 1), 1.0, 32) == (None, 0.0, {})


def test_hog_feature_and_region():
    x = W.norm(_glyph(True), 80)
    f = W.feature(x, "hog", (0.28, 0.78, 0.15, 0.65))
    nc, nr = (int(.78 * 80) - int(.28 * 80)) // 8, (int(.65 * 80) - int(.15 * 80)) // 8
    assert f.ndim == 1 and f.size == (nr - 1) * (nc - 1) * 4 * 12
    assert np.isclose(np.linalg.norm(f[:48]), 1.0, atol=1e-3)


def test_evaluate_by_book_leaves_book_out():
    d = _bank()
    saved = O.SPECS["lv"]
    O.SPECS["lv"] = SPEC
    try:
        r = W.evaluate("lv", d, margins=(0.0, 0.3))
    finally:
        O.SPECS["lv"] = saved
    assert r["cells"] == 16 and r["by_margin"][0.0] == {"right": 16, "abstain": 0, "wrong": 0}
    assert r["wrong"] == []


def test_repo_whole_banks_load_and_match_spec():
    for g, kind in (("lv", "pix"),):   # zheng 徵徴 2026-10-27 改成码位组
        sp = O.SPECS[g]
        assert sp.whole == kind and O.has_bank(g), g
        bank = O.load_bank(O.bank_path(g))
        assert set(bank) == GROUPS[g].members, g
        assert all(len(v) >= sp.min_class for v in bank.values()), g
        assert all(t.shape == (sp.size, sp.size) for v in bank.values() for t in v), g
        assert GROUPS[g].flow.solvers == ("freq", "ids") and GROUPS[g].kind == "variant", g


def test_fingerprint_covers_whole_groups():
    f = O.fingerprint(("lv", "xz"))
    assert f.startswith("ids:lv=") and ",xz=" in f
