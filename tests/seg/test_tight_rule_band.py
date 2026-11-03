"""column_text_band 写本收紧（column_warp.tight_rule_band；SJ r5「以」的左竖被当界行抹，2026-11-03）。"""
import numpy as np

from open_guji_cv.seg.profile import column_text_band

H, W = 240, 200
TIGHT = {"first_valley": True, "bar_after_min_peak": 0.5}


def _slab(fuzz: bool):
    """左缘界行 x0–3（fuzz：线边 x3–6 拖着淡毛边）；字贴着界行写：「以」左竖 x6–12，右半「人」x22–60。"""
    g = np.full((H, W), 255, np.uint8)
    g[:, 0:3] = 0
    if fuzz:
        g[::20, 3:6] = 0                   # 毛边：不归零，比左竖与「人」之间的缝还浓
    g[:, 196:200] = 0
    g[90:150, 6:12] = 0                    # 左竖
    g[60:180, 22:60] = 0                   # 右半
    g[40:200, 90:130] = 0                  # 别的字身
    return g


def test_valley_after_rule_not_window_minimum():
    g = _slab(fuzz=True)
    assert column_text_band(g)[0] >= 12                     # 缺省：取窗口最低点（左竖与「人」之间的白），左竖算带外
    assert column_text_band(g, **TIGHT)[0] <= 6


def test_stroke_not_taken_as_inner_rule():
    g = _slab(fuzz=False)
    assert column_text_band(g)[0] >= 12                     # 缺省：界行内侧孤立窄条（峰 0.25）当第二道线
    assert column_text_band(g, **TIGHT)[0] <= 6


def test_tight_still_strips_rule():
    g = np.full((H, W), 255, np.uint8)
    g[:, 0:4] = 0
    g[:, 196:200] = 0
    g[20:220, 30:170] = 0
    lo, hi = column_text_band(g, **TIGHT)
    assert 4 <= lo <= 30 and 170 <= hi <= 196
