"""Step4 图块 pad 带里邻字笔尖的剔除（2026-09-19）：`drop_pad_only_components`。

bxgb 审阅标的 contaminated 大半是这个：图块按格界外扩 8% 裁，紧裁又是图块内全部墨的
外接框，邻字压在格界外几像素的笔尖被框进来（4 页 1422 格里 161 格、中位 6px）。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import drop_pad_only_components


def _patch(h: int = 90, w: int = 100) -> np.ndarray:
    return np.full((h, w), 255, np.uint8)


def test_neighbor_tip_in_pad_is_dropped():
    p = _patch()
    p[10:70, 20:80] = 0          # 本字（格界 6..84）
    p[0:4, 30:60] = 0            # 上邻字伸进 pad 的笔尖，整体在格界之上
    p[86:90, 30:60] = 0          # 下邻字的
    out = drop_pad_only_components(p, 6, 84)
    assert (out[0:4] == 255).all() and (out[86:90] == 255).all()
    assert (out[10:70, 20:80] == 0).all()


def test_own_stroke_crossing_the_boundary_is_kept():
    """本字越界的笔画跨过格界：哪怕只沾进一像素也要留——pad 就是给它留的。"""
    p = _patch()
    p[10:70, 20:80] = 0
    p[70:88, 48:52] = 0          # 本字的竖笔从字身一直伸到格界（84）之外
    out = drop_pad_only_components(p, 6, 84)
    assert (out[84:88, 48:52] == 0).all()


def test_no_pad_is_a_noop():
    p = _patch()
    p[0:3, :] = 0
    out = drop_pad_only_components(p, 0, p.shape[0])
    assert (out == p).all()


def test_detached_component_inside_cell_is_kept():
    """格界之内、与字身分离的点（灬、丶）不归这条管。"""
    p = _patch()
    p[10:60, 20:80] = 0
    p[66:72, 30:36] = 0          # 格内的一点
    out = drop_pad_only_components(p, 6, 84)
    assert (out[66:72, 30:36] == 0).all()
