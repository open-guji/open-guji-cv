"""CNN 候选源 + RRF 融合 + 「一」兜底规则的回归。

数字来源（2026-09-05，unseen 1,327 条，异体算对）：HOG 75.5/94.7，CNN 72.4/97.6，
**RRF 86.7/98.3**（top1/top10）。rare-char 21 条 CNN 单独 top-10 100%。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.clustering.candidates import BAR_ASPECT, _bar_rule
from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates, rrf


# ── RRF ──────────────────────────────────────────────────────────
def test_rrf_prefers_agreement():
    """两源都排前面的字，应该压过只在一源排第一的字。"""
    out = rrf(["甲", "乙", "丙"], ["乙", "丁", "甲"], k=3)
    assert out[0] in ("甲", "乙")            # 两源都靠前
    assert "丁" in out or "丙" in out


def test_rrf_single_source_passthrough():
    assert rrf(["甲", "乙", "丙"], k=2) == ["甲", "乙"]


def test_rrf_ignores_scores_only_ranks():
    """RRF 只看名次——同名次同贡献，与分数无关（各源量纲不同）。"""
    a = rrf(["甲", "乙"], ["乙", "甲"], k=2)
    assert set(a) == {"甲", "乙"}


# ── 「一」兜底 ─────────────────────────────────────────────────────
def _bar(w: int = 100, h: int = 16) -> np.ndarray:
    img = np.full((h + 10, w + 10), 255, np.uint8)
    img[5:5 + h, 5:5 + w] = 0
    return img


def test_bar_rule_fills_empty_output_for_horizontal_bar():
    """扁横条 + OCR 空输出 → 补「一」。实测「一」宽高比 4.9~6.9。"""
    assert _bar_rule(_bar(100, 16), []) == [("一", 0.9)]


def test_bar_rule_keeps_confident_output():
    """OCR 有把握的输出不动——规则只兜空/低置信。"""
    assert _bar_rule(_bar(100, 16), [("二", 0.95)]) == [("二", 0.95)]


def test_bar_rule_ignores_square_patch():
    """普通方块字（宽高比 ~1）不该被改成「一」。非「一」的 596 字里 0 个超过 3.0。"""
    sq = np.full((64, 64), 255, np.uint8)
    sq[8:56, 8:56] = 0
    assert _bar_rule(sq, []) == []


def test_bar_rule_threshold_sane():
    assert 3.0 <= BAR_ASPECT <= 4.5


# ── CNN 候选源 ─────────────────────────────────────────────────────
def test_cnn_unavailable_is_silent(tmp_path):
    """没有 checkpoint 时 available=False、topk 返回空——界面退回 HOG，不报错。"""
    c = CnnCandidates(tmp_path / "nope.pt")
    assert not c.available
    assert c.topk(np.zeros((64, 64), np.uint8), ["甲"], k=3) == []


@pytest.mark.skipif(not Path(DEFAULT_CKPT).exists(), reason="没有训练好的 checkpoint")
def test_cnn_topk_contract():
    """有模型时：只返回字表内的字、概率降序、条数 ≤ k。"""
    c = CnnCandidates()
    q = np.zeros((64, 64), np.uint8)
    q[20:44, 8:56] = 1
    cs = ["一", "二", "三", "十", "土"]
    out = c.topk(q, cs, k=3)
    assert len(out) <= 3
    assert all(ch in cs for ch, _ in out)
    assert all(out[i][1] >= out[i + 1][1] for i in range(len(out) - 1))


@pytest.mark.skipif(not Path(DEFAULT_CKPT).exists()
                    or not Path("../open-guji-dataset/rare-char/items.jsonl").exists(),
                    reason="没有 checkpoint 或 rare-char 集")
def test_cnn_rare_char_top10():
    """rare-char 21 条，CNN 单独 top-10 不该掉到 85% 以下（实测 100%）。"""
    import json

    import cv2

    from open_guji_cv.clustering.font_candidates import book_charset
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.variants import are_variants

    items = [json.loads(l) for l in
             Path("../open-guji-dataset/rare-char/items.jsonl").read_text(encoding="utf-8").splitlines()]
    cs = book_charset("corpus/zongmu_wuyingdian_reference.txt",
                      [i["expected"]["char"] for i in items])
    c = CnnCandidates()
    hit = n = 0
    for it in items:
        img = cv2.imread(it["input"]["patch"], cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        n += 1
        g = it["expected"]["char"]
        top = [ch for ch, _ in c.topk(normalize_patch(img), cs, k=10)]
        hit += any(ch == g or are_variants(ch, g) for ch in top)
    assert n and hit / n >= 0.85, f"CNN rare-char top-10 = {hit}/{n}"


def test_rrf_weights_tilt_toward_heavier_source():
    """权重：CNN=2 时，CNN 第一名要压过 HOG 第一名（两源不一致的情形）。

    生产取 CNN_WEIGHT=2.0：HOG 在最难那撮上只有 47.6% top-1，等权会把 CNN 的
    正确答案拖出 top-10（rare-char 90.5% → 加权后 100%）。
    """
    from open_guji_cv.clustering.cnn_candidates import CNN_WEIGHT
    # 两源**完全不一致**时：等权是平手（各自第一名同分），加权后 CNN 第一名领先。
    # 注意 RRF 奖励「两源都靠前」——若两源在某字上一致，它会压过任一源的第一名，
    # 这是设计（见 test_rrf_prefers_agreement），不是权重的反例。
    hog = ["甲", "乙", "丙"]
    cnn = ["丁", "戊", "己"]
    wt = rrf(hog, cnn, k=3, weights=(1.0, CNN_WEIGHT))
    assert wt[0] == "丁", f"加权后 CNN 第一名该领先：{wt}"
    rev = rrf(hog, cnn, k=3, weights=(CNN_WEIGHT, 1.0))
    assert rev[0] == "甲", f"权重反过来 HOG 第一名该领先：{rev}"
    assert 1.5 <= CNN_WEIGHT <= 3.0
