"""CNN 候选源 + RRF 融合 + 「一」兜底规则的回归。

数字来源（2026-09-05，unseen 1,327 条，异体算对）：HOG 75.5/94.7，CNN 72.4/97.6，
**RRF 86.7/98.3**（top1/top10）。rare-char 21 条 CNN 单独 top-10 100%。
"""

from __future__ import annotations

import numpy as np
import pytest
import rare_char_set  # 同目录辅助：按 patch_key 解析字块图，见其 docstring

from open_guji_cv.clustering.candidates import BAR_ASPECT, _bar_rule
from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, CnnCandidates, rrf
from open_guji_cv.core.workspace import corpus_path

# 守卫要跟 `CnnCandidates.available` 同一条件——**光看 checkpoint 在不在不够**。
# torch 是可选依赖（没装时 available=False、topk 返回空，调用方退回 HOG，这是
# 设计的静默降级，见 test_cnn_unavailable_is_silent）。只守 ckpt 的话，venv 里
# 没 torch 时这些用例照跑不误，拿到的全是空列表：`len([]) <= 3`、两个空列表相等
# 之类的弱断言会**假通过**，只有 `0 < len(out)`、`hit/n >= 0.85` 这种才红——
# 同一批用例一半绿一半红，病因还看不出来。统一守 available。
CNN_OK = CnnCandidates().available
needs_cnn = pytest.mark.skipif(
    not CNN_OK, reason=f"没有 checkpoint（{DEFAULT_CKPT}）或没装 torch")


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


@needs_cnn
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


#: 批处理 vs 逐次的分数容差。**只放宽分数，字与名次照旧严格比**。
#:
#: 1e-4 在 r4 上够（实测最大 6.4e-05），换 r5 后超了（3.3e-04）：
#: 权重变了，GPU 上批处理的累加顺序差异被放大一个量级。同一份图跑三次
#: 分差完全相同——是确定性的求和顺序偏差，不是随机噪声。
#: 按设备拆：cuda 3.3e-04、cpu 2.4e-07，确认来源是 GPU 批处理。
#:
#: 与 `tests/test_console_routes.py` 的 `_SCORE_TOL = 5e-4` 同一类问题、同一个值。
#: ⚠️ 别用「round 到更少位数再比」那招——噪声骑在进位边界上照样不等
#: （那边 2026-09-15 栽过），要吃掉噪声只能比差值。
_BATCH_SCORE_TOL = 5e-4


@needs_cnn
def test_topk_batch_matches_sequential():
    """`topk_batch` 必须与逐次调用 `topk` 位级相同（2026-09-10 生僻字候选
    提速：整页字块一次前向，不能悄悄改变候选或排名）。"""
    c = CnnCandidates()
    cs = ["一", "二", "三", "十", "土", "王"]
    qs = [np.zeros((64, 64), np.uint8) for _ in range(3)]
    qs[0][20:44, 8:56] = 1
    qs[1][10:30, 10:30] = 1
    qs[2][30:50, 20:60] = 1
    seq = [c.topk(q, cs, k=4) for q in qs]
    batch = c.topk_batch(qs, cs, k=4)
    # 批处理与逐次调用的矩阵运算求和顺序不同，允许浮点噪声，
    # 但字符与排名必须完全一致。
    for s, b in zip(seq, batch):
        assert [ch for ch, _ in s] == [ch for ch, _ in b]
        for (_, ps), (_, pb) in zip(s, b):
            assert abs(ps - pb) < _BATCH_SCORE_TOL


@needs_cnn
def test_emb_topk_batch_matches_sequential():
    """同上，`emb_topk_batch` 对 `emb_topk`。"""
    c = CnnCandidates()
    cs = ["一", "二", "三", "十", "土", "王"]
    qs = [np.zeros((64, 64), np.uint8) for _ in range(3)]
    qs[0][20:44, 8:56] = 1
    qs[1][10:30, 10:30] = 1
    qs[2][30:50, 20:60] = 1
    seq = [c.emb_topk(q, cs, k=4) for q in qs]
    batch = c.emb_topk_batch(qs, cs, k=4)
    for s, b in zip(seq, batch):
        assert [ch for ch, _ in s] == [ch for ch, _ in b]
        for (_, ps), (_, pb) in zip(s, b):
            assert abs(ps - pb) < _BATCH_SCORE_TOL


@needs_cnn
@pytest.mark.skipif(not rare_char_set.available(), reason=rare_char_set.SKIP_REASON)
def test_cnn_rare_char_top10():
    """rare-char 21 条，CNN 单独 top-10 不该掉到 85% 以下（实测 100%）。"""
    from open_guji_cv.clustering.font_candidates import book_charset
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.variants import are_variants

    loaded = rare_char_set.load_items()
    cs = book_charset(str(corpus_path("zongmu_wuyingdian_reference.txt")),
                      [it["expected"]["char"] for it, _ in loaded])
    c = CnnCandidates()
    hit = n = 0
    for it, img in loaded:
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
    from open_guji_cv.clustering.cnn_candidates import (CNN_WEIGHT, EMB_WEIGHT,
                                                         HOG_WEIGHT)
    # 两源**完全不一致**时：等权是平手（各自第一名同分），加权后重的那源第一名领先。
    # 注意 RRF 奖励「两源都靠前」——若两源在某字上一致，它会压过任一源的第一名，
    # 这是设计（见 test_rrf_prefers_agreement），不是权重的反例。
    hog = ["甲", "乙", "丙"]
    cnn = ["丁", "戊", "己"]
    wt = rrf(hog, cnn, k=3, weights=(1.0, 2.0))
    assert wt[0] == "丁", f"加权后重的那源第一名该领先：{wt}"
    rev = rrf(hog, cnn, k=3, weights=(2.0, 1.0))
    assert rev[0] == "甲", f"权重反过来该换边：{rev}"
    # 生产权重的序：embedding 检索最强（91.9%）、HOG 最弱且怕磨损——扫描定的
    # 2026-09-07 起 HOG_WEIGHT 改为 0.0（不是账本漂移，是有意关停）：换真刻本切图
    # 模板后 embedding 已完全覆盖 HOG 能给的信号，HOG 检索不再参与 RRF 加权；
    # checkpoint 缺席时仍保留兜底调用路径，旧权重可随时调回（见
    # cnn_candidates.py 模块 docstring "HOG/CNN 检索批处理化" 一节）。
    assert EMB_WEIGHT >= CNN_WEIGHT >= HOG_WEIGHT >= 0


@needs_cnn
def test_emb_topk_contract_and_cache():
    """embedding 检索：只返回字表内的字、相似度降序；模板向量落盘复用。"""
    c = CnnCandidates()
    cs = ["一", "二", "三", "十", "土", "王"]
    q = np.zeros((64, 64), np.uint8)
    q[20:44, 8:56] = 1
    out = c.emb_topk(q, cs, k=4)
    assert 0 < len(out) <= 4
    assert all(ch in cs for ch, _ in out)
    assert all(out[i][1] >= out[i + 1][1] for i in range(len(out) - 1))
    # 第二次走缓存，结果一致
    assert [ch for ch, _ in c.emb_topk(q, cs, k=4)] == [ch for ch, _ in out]


def test_cls_gate_weight():
    """分类头门控：emb 前 3 名落在 classes 内的比例决定 cls 权重。

    类外字位上分类头的输出全是错的（`cache/oov_bench` 314 条实测 top-10 = 0%），
    恒权会把 embedding 的正确答案压下去——同集 emb 单源 top-1 67.8%，
    两路恒权 RRF 只剩 26.4%。
    """
    from open_guji_cv.clustering.cnn_candidates import CNN_WEIGHT, cls_gate_weight

    S = {"一", "二", "三"}
    # 前三名全在类内 → 满权重
    assert cls_gate_weight(["一", "二", "三", "x"], S) == CNN_WEIGHT
    # 全在类外 → 归零，分类头不参与
    assert cls_gate_weight(["𠀀", "𠀁", "𠀂"], S) == 0.0
    # 各半 → 按比例插值
    w = cls_gate_weight(["一", "𠀀", "二"], S)
    assert 0.0 < w < CNN_WEIGHT
    # 空 order（emb 没给候选）不该把分类头也关掉
    assert cls_gate_weight([], S) == CNN_WEIGHT
    # 空 classes（没 checkpoint）：分类头本来也没输出，给 lo 不影响结果
    assert cls_gate_weight(["一"], set()) == 0.0


def test_comp_probs_batch_contract():
    """部件袋头的概率输出：键是 checkpoint 里的 `comps`，值在 [0,1]，一图一字典。
    没 checkpoint 就跳过（needs=model）。"""
    from open_guji_cv.clustering.cnn_candidates import shared
    cnn = shared()
    if not cnn.available:
        pytest.skip("没有 CNN checkpoint")
    q = np.zeros((64, 64), np.uint8); q[16:48, 16:48] = 1
    out = cnn.comp_probs_batch([q, q])
    assert len(out) == 2 and set(out[0]) == set(cnn.comps) and cnn.comps
    assert all(0.0 <= v <= 1.0 for v in out[0].values())
    assert cnn.comp_probs_batch([]) == []

