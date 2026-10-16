# -*- coding: utf-8 -*-
"""入／人／八 字形分类器（`utils/rr_clf` + `seed_admit.rr_clf`「分歧→送审」，overview#437）。自造数据与桩模型，不读真书。"""
from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.steps.seed_admit as sa
import open_guji_cv.utils.rr_clf as rr
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1
DIM = rr.N * rr.N + rr.N + rr.N + 7


def _glyph(kind: str) -> np.ndarray:
    """灰度字块：白底黑笔画。人＝撇捺在顶端相接；八＝两笔分离；入＝相接但顶端出头。粗略即可，只测特征维度与区分度。"""
    import cv2
    g = np.full((96, 96), 255, np.uint8)
    if kind == "人":
        cv2.line(g, (48, 14), (22, 84), 0, 7); cv2.line(g, (48, 14), (78, 84), 0, 7)
    elif kind == "八":
        cv2.line(g, (40, 24), (20, 84), 0, 7); cv2.line(g, (56, 24), (80, 84), 0, 7)
    else:   # 入
        cv2.line(g, (30, 14), (52, 14), 0, 7); cv2.line(g, (52, 14), (24, 84), 0, 7); cv2.line(g, (52, 14), (78, 84), 0, 7)
    return g


def test_features_shape_and_blank():
    f = rr.features(_glyph("人"))
    assert f is not None and f.shape == (DIM,) and f.dtype == np.float32
    assert rr.features(np.full((96, 96), 255, np.uint8)) is None          # 白板没有字形
    assert rr.features(np.zeros((0, 0), np.uint8)) is None


def test_features_distinguish_top_structure():
    # hand 特征的第 3 项是顶部带连通块数：八 的顶部是两笔分离
    h = {k: rr.features(_glyph(k))[-7:] for k in "人入八"}
    assert h["八"][2] >= 2 and h["人"][2] == 1


def test_quality_gate():
    g = _glyph("人")
    assert not rr.gated(rr.quality(g))
    noisy = g.copy(); noisy[:, :2] = 0                                     # 贴左边的竖线
    assert rr.gated(rr.quality(noisy))
    assert rr.gated(None)


def test_forest_inference_matches_hand_tree(tmp_path):
    # 一棵树：feature0 <= 0.5 → 叶 [1,0,0,0]，否则 [0,1,0,0]；两棵树平均
    left = np.array([1, -1, -1], np.int32); right = np.array([2, -1, -1], np.int32)
    feat = np.array([0, -2, -2], np.int32); thr = np.array([0.5, 0, 0], np.float64)
    val = np.array([[0, 0, 0, 0], [1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
    f = rr.Forest(np.concatenate([left, left + 3 * (left >= 0)]), np.concatenate([right, right + 3 * (right >= 0)]),
                  np.concatenate([feat, feat]), np.concatenate([thr, thr]), np.concatenate([val, val]), np.array([0, 3]))
    P = f.proba(np.array([[0.0], [1.0]], np.float32))
    assert P[0].tolist() == [1, 0, 0, 0] and P[1].tolist() == [0, 1, 0, 0]


def test_export_roundtrip_matches_sklearn(tmp_path):
    sk = pytest.importorskip("sklearn.ensemble")
    rng = np.random.RandomState(0)
    X = rng.rand(120, 6).astype(np.float32); y = (X[:, 0] > 0.5).astype(int) + 2 * (X[:, 1] > 0.5).astype(int)
    m = sk.RandomForestClassifier(20, min_samples_leaf=2, random_state=0).fit(X, y)
    p = tmp_path / "f.npz"; rr.export_forest(m, p)
    assert np.abs(rr.Forest.load(p).proba(X) - m.predict_proba(X)).max() < 1e-6


def test_classify_decision_rules(monkeypatch):
    class Stub:
        def __init__(self, P): self.P = np.array([P])
        def proba(self, X): return self.P
    g = _glyph("人")
    for P, want in (([0.8, 0.1, 0.05, 0.05], "人"), ([0.3, 0.45, 0.2, 0.05], None),          # 最大概率 < 0.5 弃权
                    ([0.1, 0.1, 0.1, 0.7], None)):                                           # 判为「其他」弃权
        monkeypatch.setattr(rr, "_model", lambda path, P=P: Stub(P))
        assert rr.classify(g, "x")["pick"] == want
    monkeypatch.setattr(rr, "_model", lambda path: Stub([0.9, 0.05, 0.03, 0.02]))
    noisy = g.copy(); noisy[:, :2] = 0
    c = rr.classify(noisy, "x")
    assert c["gated"] and c["pick"] is None                                                    # 质量闸不过不给字


# ---- seed_admit 接线 ----
def test_params_off_not_in_dump_and_fingerprint():
    d = SeedAdmitParams().model_dump()
    assert SeedAdmitParams().rr_clf is False and not any(k.startswith("rr_clf") for k in d)
    on = SeedAdmitParams(rr_clf=True).model_dump()
    assert on["rr_clf"] is True and on["rr_clf_p"] == 0.5 and on["rr_clf_fingerprint"]


def _ctx(tmp_path, monkeypatch, params):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params={"seed_admit": params}, log=lambda s: None)


def _run(ctx, char="人"):
    recs = [dict(slot=1, verdict="same", cov=1.0, wmax=0.0, char="山", candidates=[("山", 1.0)]),
            dict(slot=2, verdict="same", cov=1.0, wmax=0.0, char=char, candidates=[(char, 1.0)]),
            dict(slot=3, verdict="same", cov=1.0, wmax=0.0, char="水", candidates=[("水", 1.0)])]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=1, align_char="山"), dict(slot=2, align_char=char), dict(slot=3, align_char="水")], col=COL))
    sa_ = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in sa_.columns for r in cc.chars}[2]


def _stub(monkeypatch, pick, gated=False, p=0.9):
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: _glyph("人"))
    monkeypatch.setattr(rr, "classify", lambda g, m=None, t=0.5: {"probs": {"人": p}, "pick": pick, "gated": gated, "p": p})


def test_off_by_default_does_nothing(tmp_path, monkeypatch):
    _stub(monkeypatch, "入")
    r = _run(_ctx(tmp_path, monkeypatch, SeedAdmitParams()))
    assert r.admit and r.char == "人" and "rr_clf" not in r.evidence


def test_disagreement_demotes_without_changing_char(tmp_path, monkeypatch):
    _stub(monkeypatch, "入")
    r = _run(_ctx(tmp_path, monkeypatch, SeedAdmitParams(rr_clf=True)))
    assert not r.admit and "rr_clf_disagree" in r.doubts and r.char == "人"
    assert r.evidence["rr_clf"]["pick"] == "入"


def test_agreement_or_abstain_keeps_admit(tmp_path, monkeypatch):
    for pick in ("人", None):
        _stub(monkeypatch, pick)
        r = _run(_ctx(tmp_path, monkeypatch, SeedAdmitParams(rr_clf=True)))
        assert r.admit and r.char == "人" and r.evidence["rr_clf"]["pick"] == pick


def test_cell_outside_group_not_touched(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: called.append(1) or _glyph("人"))
    r = _run(_ctx(tmp_path, monkeypatch, SeedAdmitParams(rr_clf=True)), char="山")
    assert r.admit and not called


def test_patch_missing_skip_records(tmp_path, monkeypatch):
    def boom(*a, **k): raise sa.PatchUnavailable("无图")
    monkeypatch.setattr(sa, "_page_patch", boom)
    r = _run(_ctx(tmp_path, monkeypatch, SeedAdmitParams(rr_clf=True, patch_missing="skip")))
    assert r.admit and "rr_clf" in r.evidence.get("patch_missing", [])
