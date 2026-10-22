"""Step4 图块 pad 带里邻字笔尖的剔除（2026-09-19）：`drop_pad_only_components`。

bxgb 审阅标的 contaminated 大半是这个：图块按格界外扩 8% 裁，紧裁又是图块内全部墨的
外接框，邻字压在格界外几像素的笔尖被框进来（4 页 1422 格里 161 格、中位 6px）。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import clip_unions_at_line, drop_neighbor_parts, drop_pad_only_components


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


def _ctx(h: int = 270, w: int = 100) -> np.ndarray:
    return np.full((h, w), 255, np.uint8)


def test_neighbor_part_crossing_mostly_outside_is_dropped():
    """上字断开的底横带个小钩伸过格界（90）：墨大半在格界外，从本格抹掉（vol05「上/下」）。"""
    c = _ctx()
    c[20:78, 20:80] = 0          # 上字
    c[80:86, 10:50] = 0          # 上字底横的左段（与字身断开）
    c[86:94, 30:33] = 0          # 小钩伸过格界
    c[100:170, 20:80] = 0        # 本字
    patch = c[81:189].copy()     # 图块 = 格（90..180）上下各 9px pad
    out = drop_neighbor_parts(patch, c, 81, 90, 180, 90)
    assert (out[:94 - 81] == 255).all()
    assert (out[100 - 81:170 - 81, 20:80] == 0).all()


def test_own_top_dot_crossing_mostly_outside_is_kept():
    """格界偏低，下字顶上的点大半在界外，可它紧挨着本字（音、言、序）：留着。"""
    c = _ctx()
    c[20:70, 20:80] = 0          # 上字
    c[84:93, 45:52] = 0          # 本字的点，大半在格界（90）之上
    c[95:170, 20:80] = 0         # 本字
    out = drop_neighbor_parts(c[81:189].copy(), c, 81, 90, 180, 90)
    assert (out[84 - 81:93 - 81, 45:52] == 0).all()


def test_own_part_crossing_mostly_inside_is_kept():
    c = _ctx()
    c[100:170, 20:80] = 0
    c[174:186, 30:60] = 0        # 本字底横，大半在格界（180）以内
    out = drop_neighbor_parts(c[81:189].copy(), c, 81, 90, 180, 90)
    assert (out[174 - 81:186 - 81, 30:60] == 0).all()


def test_touching_block_reaching_ctx_edge_is_kept():
    """碰到上下各一格的列条边的是粘连长块，照旧按格界切。"""
    c = _ctx()
    c[0:100, 45:50] = 0          # 从列条顶一直下来
    c[100:170, 20:80] = 0
    out = drop_neighbor_parts(c[81:189].copy(), c, 81, 90, 180, 90)
    assert (out[0:19, 45:50] == 0).all()


def test_side_with_seam_is_not_checked():
    c = _ctx()
    c[80:86, 10:50] = 0
    c[86:94, 30:33] = 0
    c[100:170, 20:80] = 0
    out = drop_neighbor_parts(c[81:189].copy(), c, 81, 90, 180, 90, top=False)
    assert (out[86 - 81:94 - 81, 30:33] == 0).all()


def test_deep_part_is_kept_even_if_mostly_outside():
    """伸进本格深（两字粘成一块，「爲/兵」）：墨大半在界外也不挪，挪了会挖掉本字的笔画。"""
    c = _ctx()
    c[20:70, 20:80] = 0
    c[70:92, 40:70] = 0          # 上字的下半，大半在格界（90）之上
    c[92:110, 60:63] = 0         # 粘着的本字一笔，伸进格内 20px（> 0.1 格）
    c[115:170, 20:80] = 0
    out = drop_neighbor_parts(c[81:189].copy(), c, 81, 90, 180, 90)
    assert (out[92 - 81:110 - 81, 60:63] == 0).all()


def test_union_deep_on_both_sides_is_clipped_at_the_line():
    """两字粘成一块、跨格界两边都伸得深（「家」的竖钩连「之」的点）：本格只留格界以内的半边。"""
    c = _ctx()
    c[20:90, 45:50] = 0          # 上字的竖钩，一直伸到格界（90）
    c[90:120, 40:70] = 0         # 连着下字的点与横
    c[130:170, 20:80] = 0
    out = drop_neighbor_parts(c[81:189].copy(), c, 81, 90, 180, 90)
    out = clip_unions_at_line(out, c, 81, 90, 180, 90)
    assert (out[:90 - 81] == 255).all()
    assert (out[90 - 81:120 - 81, 40:70] == 0).all()


def test_own_overshoot_is_not_clipped():
    """本字的笔画越过格界一小截（不到 0.1 格）：pad 留着它，不切。"""
    c = _ctx()
    c[100:186, 45:50] = 0        # 本字的竖越过格界（180）6px
    out = clip_unions_at_line(c[81:189].copy(), c, 81, 90, 180, 90)
    assert (out[180 - 81:186 - 81, 45:50] == 0).all()
