"""取块窗口要认 Step3 的折线（2026-09-20）。

Step3 选中折线后写进 `seam_top`/`seam_bottom`，而矩形 `y_top`/`y_bottom` 仍是
DP 那条直线——两者可以差几十像素。取块窗口此前只读矩形边界：

  bxgb p31c9 / p45c2 末格「十」：人裁把切点定在 1434（真字缝），矩形边界却是
  1462，窗口从 1462 起裁，「十」的横笔整条落在窗口**之外**，图块只剩一竖，
  人裁标成「字形不完整」。

`mask_outside` 救不回来：它只能抹掉窗口内不属于本格的墨，**抹不出窗口外没裁
进来的墨**。所以窗口取矩形与折线的并集；折线外的墨仍由 `mask_outside` 抹掉，
归属判断仍归折线，与「格界严格信任 Step3」不冲突。
"""
from __future__ import annotations

from open_guji_cv.clustering.extractor import _cell_bottom, _cell_top, _seam_span


def test_rectangle_only_cell_is_unchanged():
    c = {"y_top": 100.0, "y_bottom": 170.0}
    assert _cell_top(c) == 100.0
    assert _cell_bottom(c) == 170.0


def test_seam_above_rectangle_widens_the_window():
    """p31c9 末格的形状：折线 1434 比矩形上界 1462 高 28px。"""
    c = {"y_top": 1462.0, "y_bottom": 1522.0, "seam_top": [1434] * 19}
    assert _cell_top(c) == 1434.0, "折线更高时窗口要开上去，否则横笔裁不进来"
    assert _cell_bottom(c) == 1522.0


def test_seam_below_rectangle_widens_the_window():
    c = {"y_top": 1381.0, "y_bottom": 1434.0, "seam_bottom": [1462] * 19}
    assert _cell_bottom(c) == 1462.0
    assert _cell_top(c) == 1381.0


def test_seam_inside_rectangle_does_not_shrink_it():
    """并集，不是替换——折线在矩形**内**时窗口不能跟着缩，那会裁掉本格的墨。"""
    c = {"y_top": 100.0, "y_bottom": 200.0,
         "seam_top": [120] * 19, "seam_bottom": [180] * 19}
    assert _cell_top(c) == 100.0
    assert _cell_bottom(c) == 200.0


def test_slanted_seam_uses_its_extreme():
    """折线是逐 x 的数组，斜着走时要取极值，不能只看第一个点。"""
    c = {"y_top": 500.0, "y_bottom": 560.0, "seam_top": [495, 490, 486, 482, 478]}
    assert _cell_top(c) == 478.0
    c2 = {"y_top": 500.0, "y_bottom": 560.0, "seam_bottom": [561, 566, 570, 575]}
    assert _cell_bottom(c2) == 575.0


def test_empty_and_none_seams_are_ignored():
    for bad in (None, [], [None]):
        c = {"y_top": 10.0, "y_bottom": 80.0, "seam_top": bad, "seam_bottom": bad}
        assert _cell_top(c) == 10.0 and _cell_bottom(c) == 80.0
    assert _seam_span(None) is None
    assert _seam_span([]) is None
