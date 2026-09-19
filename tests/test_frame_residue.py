"""`frame_residue`：清理后端部还剩不剩版框墨（闸2 判据）。

判据本身是在 bxgb 全书 2052 个端口上按 **trim 档位** 标定的（d/e 两档 1065 个
端口零误报）。这里钉的是它的**形态判别力**：只认「横贯整列宽 + 连续若干行」
的框线，不认字的横笔——这正是被证伪的「端部峰值」候选做不到的事
（削干净的 d/e 档峰值 p50 也有 0.43~0.47，与漏判的 c 档 0.548 重叠）。

另有一条独立验证记在这里，因为它不是构造出来的而是实跑撞上的：
判据标定只用了 trim 档位，事后拿它去查「末格（slot 21）把下版框吞进去」
的列，bxgb 全书 92 个末格拉长列里 **9 个含满宽段的全部命中（9/9）**，
另 83 个散墨（末字下伸，bottom_slack 的预期行为）一个没误报。
标定口径与这条查法完全独立，所以这 9/9 是真验证不是自证。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.steps.column_warp import (FRAME_RESIDUE_MIN_RUN, frame_residue)

BAND = (10, 110)


def _blank(h: int = 400, w: int = 120) -> np.ndarray:
    return np.full((h, w), 255, dtype=np.uint8)


def test_clean_column_has_no_residue():
    assert frame_residue(_blank(), BAND) == (0, 0)


def test_full_width_bar_at_top_is_caught():
    g = _blank()
    g[5:5 + FRAME_RESIDUE_MIN_RUN + 2, :] = 0      # 满宽横线
    top, bot = frame_residue(g, BAND)
    assert top >= FRAME_RESIDUE_MIN_RUN
    assert bot == 0


def test_full_width_bar_at_bottom_is_caught():
    g = _blank()
    g[-8:-2, :] = 0
    top, bot = frame_residue(g, BAND)
    assert top == 0
    assert bot >= FRAME_RESIDUE_MIN_RUN


def test_character_stroke_is_not_a_frame():
    """字的横笔：够黑、够连续，但**不满宽**——判据不该认它。

    这是与被证伪的「端部峰值」候选的分水岭：按峰值量，这根笔画的行墨占比
    0.6 会和真框线一样高。
    """
    g = _blank()
    g[5:15, 30:90] = 0              # 占带宽 60/100 = 0.6 < 0.85
    assert frame_residue(g, BAND) == (0, 0)


def test_thin_bar_below_min_run_is_ignored():
    """满宽但只有 1~2 行：够不着 min_run，不算框线。"""
    g = _blank()
    g[5:5 + FRAME_RESIDUE_MIN_RUN - 1, :] = 0
    top, _ = frame_residue(g, BAND)
    assert top < FRAME_RESIDUE_MIN_RUN


def test_only_measures_inside_the_band():
    """带外本来就是界行，必须不参与——否则每一列都会被判成有残框。"""
    g = _blank()
    g[5:20, :BAND[0]] = 0           # 只在左界行位置涂黑
    g[5:20, BAND[1]:] = 0
    assert frame_residue(g, BAND) == (0, 0)


def test_probe_depth_limits_how_far_in_it_looks():
    """列中部的满宽段不算残框——那是内容，不是端部没削干净。"""
    g = _blank(h=400)
    g[190:205, :] = 0
    assert frame_residue(g, BAND) == (0, 0)


def test_degenerate_band_returns_zero():
    """band 空或倒置：返回 0 而不是炸——老产物里出现过 b1 <= b0。"""
    assert frame_residue(_blank(), (50, 50)) == (0, 0)
    assert frame_residue(_blank(), (90, 10)) == (0, 0)
    assert frame_residue(np.zeros((0, 0), dtype=np.uint8), BAND) == (0, 0)
