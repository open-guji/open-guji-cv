"""jiazhu_split 单测：单格缝判据、列上下文连段、段端收编，用合成图块验证。

外加一条**漂移护栏**：常量与生产 `clustering/extractor.py` 逐个对齐——这套
阈值是生产在两册实审里踩出来的，迁移过来是副本，两边任何一侧改了值都应该
让这条测试红掉、逼人显式处理（见 `jiazhu_split` 模块头的对应关系表）。
"""
import numpy as np
import pytest

from open_guji_cv.utils import jiazhu_split as jz

W = 185          # 列距量级（vol02 实测 184px）
H = 110          # 字距量级


def _blank(h: int = H, w: int = W) -> np.ndarray:
    return np.full((h, w), 255, dtype=np.uint8)


def _box(img, x0, x1, y0, y1, v=0):
    img[y0:y1, x0:x1] = v
    return img


def _jiazhu_patch(seam: int = 92, w: int = W) -> np.ndarray:
    """双列小字格：缝左右各一个小字，合起来跨度占满列距。"""
    p = _blank(w=w)
    _box(p, 15, seam - 7, 20, 90)      # b 侧（左子列）
    _box(p, seam + 8, w - 15, 20, 90)  # a 侧（右子列）
    return p


def _single_char_patch() -> np.ndarray:
    """普通正文字：居中、跨度只占列距的 0.6 左右。"""
    p = _blank()
    _box(p, 37, 148, 15, 95)
    return p


# ── 单格判据 ────────────────────────────────────────────────


def test_gap_center_finds_seam_of_double_column_cell():
    got = jz.gap_center(_jiazhu_patch(seam=92), ref_w=W)
    assert got is not None
    cx, strength = got
    assert abs(cx - 92) <= 4
    assert strength > jz.CC_MIN


def test_gap_center_rejects_normal_centered_char():
    # 跨度只占 0.6 列距——这是普通字与夹注唯一不重叠的量
    assert jz.gap_center(_single_char_patch(), ref_w=W) is None


def test_gap_center_rejects_wide_char_without_real_seam():
    # 跨度够宽但没有 GAP_MIN 以上的中缝（部首缝只有 2px）
    p = _blank()
    _box(p, 12, 96, 15, 95)
    _box(p, 98, W - 12, 15, 95)
    assert jz.gap_center(p, ref_w=W) is None


def test_gap_center_ruler_is_the_argument_not_the_patch_width():
    """尺子必须是传进来的列距，不是图块宽度——生产为此栽过（窗口一宽比值
    就掉，同一段夹注反而判不出来）。"""
    p = _jiazhu_patch(seam=92)
    wide = np.concatenate([p, _blank(w=60)], axis=1)   # 右边补一截空白
    assert jz.gap_center(wide, ref_w=W) is not None    # 给了列距：照常判出
    assert jz.gap_center(wide) is None                 # 退回图块宽度：漏判


# ── 列上下文 ────────────────────────────────────────────────


def test_link_runs_needs_min_run_and_alignment():
    lone = [(3, (92.0, 4000.0))]
    assert jz.link_runs(lone) == {}                       # 孤格不算夹注
    pair = [(3, (92.0, 4000.0)), (4, (94.0, 4000.0))]
    assert set(jz.link_runs(pair)) == {3, 4}
    off = [(3, (92.0, 4000.0)), (4, (92.0 + jz.ALIGN + 5, 4000.0))]
    assert jz.link_runs(off) == {}                        # 缝对不齐


def test_link_runs_bridges_single_unmeasured_cell():
    """段里个别行单侧墨太少、单格判据落空，不该把连段拦腰截断。"""
    ents = [(3, (90.0, 4000.0)), (4, None), (5, (94.0, 4000.0))]
    runs = jz.link_runs(ents)
    assert set(runs) == {3, 4, 5}
    assert runs[4] == pytest.approx(92.0)                 # 桥接格用邻格均值


def test_link_runs_does_not_bridge_two_in_a_row():
    ents = [(3, (90.0, 4000.0)), (4, None), (5, None), (6, (94.0, 4000.0))]
    assert set(jz.link_runs(ents)) == set()               # 防桥接自我扩散


def test_link_runs_vetoes_noise_run_by_median_strength():
    """纸面碎点段 span/缝/均衡全能骗过，只有连通体结构分得开。"""
    noise = [(i, (92.0, 300.0)) for i in range(3, 10)]
    assert jz.link_runs(noise) == {}
    thin = [(3, (92.0, 300.0)), (4, (92.0, 4000.0)), (5, (92.0, 4000.0))]
    assert set(jz.link_runs(thin)) == {3, 4, 5}           # 单格薄不卡，看段中位


# ── 段端收编 ────────────────────────────────────────────────


def test_adopt_run_tails_single_char_tail_emits_only_a():
    """奇数字末行：只有右半（a 侧）一个小字，跨度过不了 SPAN_T。"""
    tail = _blank()
    _box(tail, 100, W - 15, 20, 90)
    patches = {3: _jiazhu_patch(), 4: _jiazhu_patch(), 5: tail}
    runs, tail_a = jz.adopt_run_tails({3: 92.0, 4: 92.0}, patches)
    assert set(runs) == {3, 4, 5}
    assert tail_a == {5}


def test_adopt_run_tails_full_last_row_splits_normally():
    """末行两个小字都在，只是合起来不够跨度——正常拆 a/b，不能压制 b 半。"""
    tail = _blank()
    _box(tail, 40, 85, 30, 80)          # b 侧真笔画（连通体远大于 ROW_B_CC）
    _box(tail, 100, 160, 30, 80)
    patches = {3: _jiazhu_patch(), 4: _jiazhu_patch(), 5: tail}
    runs, tail_a = jz.adopt_run_tails({3: 92.0, 4: 92.0}, patches)
    assert set(runs) == {3, 4, 5}
    assert tail_a == set()              # 两半都发


def test_adopt_run_tails_leaves_normal_body_char_alone():
    """全尺寸正文窄字居中、缝带上有墨，两条收编判据都过不了。"""
    patches = {3: _jiazhu_patch(), 4: _jiazhu_patch(), 5: _single_char_patch()}
    runs, tail_a = jz.adopt_run_tails({3: 92.0, 4: 92.0}, patches)
    assert set(runs) == {3, 4}
    assert tail_a == set()


def test_adopt_run_tails_skips_blank_cells():
    patches = {3: _jiazhu_patch(), 4: _jiazhu_patch(), 5: _blank()}
    runs, _ = jz.adopt_run_tails({3: 92.0, 4: 92.0}, patches, eligible={3, 4})
    assert set(runs) == {3, 4}


# ── 漂移护栏 ────────────────────────────────────────────────


def test_constants_match_production_extractor():
    """迁移是副本，不是重写：两边阈值必须逐个相等（见模块头对应关系表）。"""
    from open_guji_cv.clustering import extractor as ex

    assert jz.INK_THRESHOLD == ex.BINARY_THRESHOLD_PATCH
    assert jz.SPAN_T == ex.JIAZHU_SPAN_T
    assert jz.GAP_MIN == ex.JIAZHU_GAP_MIN
    assert jz.MASS_W == ex.JIAZHU_MASS_W
    assert jz.ALIGN == ex.JIAZHU_ALIGN
    assert jz.MIN_RUN == ex.JIAZHU_MIN_RUN
    assert jz.CC_MIN == ex.JIAZHU_CC_MIN
    assert jz.TAIL_MIN_INK == ex.JZ_TAIL_MIN_INK
    assert jz.TAIL_A_FRAC == ex.JZ_TAIL_A_FRAC
    assert jz.TAIL_GAP_BAND == ex.JZ_TAIL_GAP_BAND
    assert jz.TAIL_GAP_FRAC == ex.JZ_TAIL_GAP_FRAC
    assert jz.ROW_B_CC == ex.JZ_ROW_B_CC


def test_link_runs_matches_production_on_same_input():
    """连段逻辑本身也对齐生产实现（同输入同输出）。"""
    from open_guji_cv.clustering.extractor import flag_jiazhu_runs

    cases = [
        [(3, (92.0, 4000.0)), (4, (94.0, 4000.0)), (5, None), (6, (93.0, 4000.0))],
        [(1, (90.0, 300.0)), (2, (90.0, 300.0)), (3, (90.0, 300.0))],
        [(7, (10.0, 4000.0)), (8, (60.0, 4000.0))],
    ]
    for ents in cases:
        assert jz.link_runs(ents) == flag_jiazhu_runs(ents)
