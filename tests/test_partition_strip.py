"""Step4 整列归属图（2026-10-22）：`partition_strip` 把每个墨像素至多分给一格。

此前图块按格界外扩 8% 裁、再逐块清理 pad 里的邻字墨（`drop_pad_only_components`、
`drop_neighbor_parts`、`clip_unions_at_line`），跨格界的连通体常被两格各带走一截。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import partition_strip

H = 90   # 格高；列条三格 [0,90) [90,180) [180,270)


def _strip(w: int = 100) -> np.ndarray:
    return np.full((3 * H, w), 255, np.uint8)


def _owner(s: np.ndarray, seam_at: int | None = None, top: int = 0, bot: int = 3 * H) -> np.ndarray:
    """seam_at：第几条格界（1 = 第 0/1 格之间）是 Step3 的折线。"""
    w = s.shape[1]
    edges = [max(top, 0), H, 2 * H, min(bot, 3 * H)]
    bounds = [(np.full(w, edges[i]), np.full(w, edges[i + 1]), seam_at == i, seam_at == i + 1) for i in range(3)]
    return partition_strip(s, bounds, H)


def test_neighbor_tip_in_pad_stays_with_its_cell():
    s = _strip()
    s[20:70, 20:80] = 0          # 上字
    s[84:89, 30:60] = 0          # 上字压在格界上沿的笔尖（落在下一格的 pad 里）
    s[100:170, 20:80] = 0        # 本字
    o = _owner(s)
    assert (o[84:89, 30:60] == 0).all() and (o[100:170, 20:80] == 1).all()


def test_ink_outside_every_cell_belongs_to_none():
    s = _strip()
    s[0:4, 30:60] = 0            # 版框带里的渣，不沾任何格
    s[20:70, 20:80] = 0
    o = _owner(s, top=10)
    assert (o[0:4, 30:60] == -1).all()


def test_neighbor_small_part_goes_to_the_nearer_char():
    """上字断开的底横带个小钩伸过格界（90）：整块归离得近的上字（vol05「上/下」）。"""
    s = _strip()
    s[20:78, 20:80] = 0          # 上字
    s[80:86, 10:50] = 0          # 上字底横的左段（与字身断开）
    s[86:94, 30:33] = 0          # 小钩伸过格界
    s[100:170, 20:80] = 0        # 本字
    o = _owner(s)
    assert (o[80:94, 10:50][s[80:94, 10:50] == 0] == 0).all()


def test_own_top_dot_above_the_line_stays_with_its_char():
    """格界偏低，下字顶上的点大半在界外，可它紧挨着本字（音、言、序）。"""
    s = _strip()
    s[20:70, 20:80] = 0
    s[84:93, 45:52] = 0          # 本字的点，大半在格界（90）之上
    s[95:170, 20:80] = 0
    o = _owner(s)
    assert (o[84:93, 45:52] == 1).all()


def test_own_overshoot_is_kept_whole():
    """本字的笔画越过格界一小截：整笔归本字，邻格那边不分走。"""
    s = _strip()
    s[100:186, 45:50] = 0        # 竖越过格界（180）6px
    s[200:260, 20:80] = 0
    o = _owner(s)
    assert (o[100:186, 45:50] == 1).all()


def test_union_deep_on_both_sides_is_split_at_the_line():
    """两字粘成一块、两边都伸得深（「家」的竖钩连「之」的点）：按格界切开，各留各的。"""
    s = _strip()
    s[20:90, 45:50] = 0          # 上字的竖钩，一直伸到格界
    s[90:120, 40:70] = 0         # 连着下字的点与横
    s[130:170, 20:80] = 0
    o = _owner(s)
    assert (o[20:90, 45:50] == 0).all() and (o[90:120, 40:70] == 1).all()


def test_deep_stroke_of_this_char_is_not_moved():
    """伸进本格深的一笔粘着上字（「爲/兵」）：不整块挪给上字，切开后本格留着它。"""
    s = _strip()
    s[20:70, 20:80] = 0
    s[70:92, 40:70] = 0          # 上字的下半
    s[92:110, 60:63] = 0         # 粘着的本字一笔，伸进格内 20px（> 0.1 格）
    s[115:170, 20:80] = 0
    o = _owner(s)
    assert (o[92:110, 60:63] == 1).all() and (o[70:90, 40:70] == 0).all()


def test_seam_boundary_is_split_strictly():
    """Step3 选了折线的格界：折线已分过部件，跨线的一律按线切。"""
    s = _strip()
    s[20:78, 20:80] = 0
    s[80:86, 10:50] = 0
    s[86:94, 30:33] = 0
    s[100:170, 20:80] = 0
    o = _owner(s, seam_at=1)
    assert (o[90:94, 30:33] == 1).all() and (o[86:90, 30:33] == 0).all()


def test_each_ink_pixel_has_at_most_one_cell():
    s = _strip()
    s[60:120, 40:60] = 0
    o = _owner(s)
    assert ((o >= 0) == (s < 128)).all()
