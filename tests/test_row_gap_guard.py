"""切点白缝护栏 `row_boundaries._gap_guard`／`_gap_corridor`（cut_gap_guard，史記 r76，A22 2026-11-17）：数据自造。"""
from types import SimpleNamespace

import numpy as np

from open_guji_cv.impl.keben import row_boundaries as rb


def _ink():
    """宽 100：上字 y 20–85，上字底横 y 90–100（与字身隔 5 行白），字缝 y 100–150，下字 y 150–220。"""
    ink = np.zeros((240, 100), bool)
    ink[20:85, 30:70] = True
    ink[90:100, 10:90] = True
    ink[150:220, 30:70] = True
    return ink


def _c(y=None):
    return SimpleNamespace(y=y)


def test_corridor_straight_in_gap_vs_narrow_gap():
    ink = _ink()
    assert rb._gap_corridor(ink, None, 125, 100) >= 50          # 字缝里的直线
    assert rb._gap_corridor(ink, [87] * 100, 87, 100) <= 6     # 上字身与底横之间的窄缝


def test_guard_moves_off_narrow_gap_to_word_gap():
    ink = _ink()
    cands = [_c(None), _c([87] * 100)]                          # 0 直线在字缝（y 125），1 U-Net 改选的窄缝
    assert rb._gap_guard(cands, 1, "unet", ink, 125.0, 100.0, 0.08) == (0, "gap")
    assert rb._gap_guard(cands, 1, "unet", ink, 125.0, 100.0, 0.0) == (1, "unet")      # 关
    assert rb._gap_guard(cands, 1, "human", ink, 125.0, 100.0, 0.08) == (1, "human")   # 人裁不动


def test_guard_keeps_chosen_in_gap_and_skips_inked_target():
    ink = _ink()
    cands = [_c(None), _c([87] * 100)]
    assert rb._gap_guard(cands, 0, "rule", ink, 125.0, 100.0, 0.08) == (0, "rule")     # 选中的已在白缝
    ink2 = ink.copy()
    ink2[120:130, 40:60] = True                                  # 字缝里那条直线压了 20 列墨：不换过去
    assert rb._gap_guard(cands, 1, "unet", ink2, 125.0, 100.0, 0.08) == (1, "unet")
