"""折线切分（utils/seam.py）：最小墨量缝 + 按缝掩膜。

场景：上字有一笔往下拖、下字有一笔往上探，两笔在水平投影上重叠——任何一条直线都穿墨，
但绕一下就能无墨通过。这是用户 2026-09-05 在 400 条金标里看出来的典型。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils.seam import find_seam, mask_outside, seam_ink


def _two_glyphs(h=80, w=60):
    """ink: 上字主体 5..27 行；一笔从 (28..45, x 10..14) 下垂；下字主体 48..74；一笔从 (34..47, x 40..46) 上探。
    直线 y=37 同时穿过下垂笔与上探笔；折线可以在 x 10..14 绕到 46/47（下垂笔之下、下字主体之上），
    在 x 40..46 绕到 33 以上（上探笔之上、上字主体之下）。
    """
    ink = np.zeros((h, w), bool)
    ink[5:28, 8:52] = True
    ink[28:46, 10:15] = True          # 上字下垂笔，到 45 行
    ink[48:75, 8:52] = True
    ink[34:48, 40:47] = True          # 下字上探笔，到 34 行
    return ink


def test_seam_avoids_ink_where_a_straight_line_cannot():
    ink = _two_glyphs()
    y = 37
    assert ink[y].any()                          # 直线穿墨
    seam = find_seam(ink, y, band=12)
    assert seam_ink(ink, seam) == 0, seam         # 折线无墨
    assert np.abs(seam - y).max() <= 12           # 不出走廊
    # 两端无墨处不强求贴着直线：转折有代价、离线只有极小的平局项，DP 会直接从绕行高度起步。
    # 这对裁片无害（那里本来没墨），金标比对用"缝与折线最大偏差"而不是端点。


def test_seam_stays_on_line_when_line_is_clean():
    ink = np.zeros((60, 40), bool)
    ink[5:25, 5:35] = True
    ink[35:55, 5:35] = True
    seam = find_seam(ink, 30, band=12)
    assert (seam == 30).all()


def test_mask_outside_removes_neighbour_pixels_only():
    ink = _two_glyphs()
    y = 37
    seam = find_seam(ink, y, band=12)
    patch = np.where(ink, 0, 255).astype(np.uint8)   # 整幅当"下格裁片"，y0=0, x0=0
    lower = mask_outside(patch, seam_top=seam, seam_bottom=None, y0=0, x0=0)
    upper = mask_outside(patch, seam_top=None, seam_bottom=seam, y0=0, x0=0)
    # 下格裁片里不再有上字主体；上格裁片里不再有下字主体
    assert not (lower[5:28] < 128).any()
    assert not (upper[48:75] < 128).any()
    # 下垂笔归上格、上探笔归下格
    assert (upper[28:46, 10:15] < 128).all()
    assert (lower[34:48, 40:47] < 128).all()


def test_segment_column_keeps_straight_cut_when_seam_cannot_avoid_ink():
    """一道贯穿全宽的粗横杠：任何折线都穿墨 → 不存缝，格线仍是直线（seam_ink > SEAM_MAX_INK）。"""
    from open_guji_cv.utils.seam import SEAM_MAX_INK, find_seam, seam_ink
    ink = np.zeros((60, 40), bool)
    ink[20:40, :] = True          # 20 行厚的横杠横贯整宽
    seam = find_seam(ink, 30, band=8)
    assert seam_ink(ink, seam) > SEAM_MAX_INK
