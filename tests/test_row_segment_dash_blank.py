# -*- coding: utf-8 -*-
"""列端虚线残段记空白（segment_column dash_blank，overview#376 后续，缺省关）。"""
import numpy as np

from open_guji_cv.utils import row_boundaries as RB

SLOT_H, N = 60, 6


def _column():
    img = np.full((SLOT_H * N + 20, 80), 255, np.uint8)
    for k in range(N):
        y0 = 10 + k * SLOT_H + 12
        img[y0:y0 + 36, 20:60] = 0               # 方块字
    # 首格：只剩一小撮窄短的虚线残段
    img[10:10 + SLOT_H, 20:60] = 255
    img[10 + 12:10 + 12 + 16, 38:42] = 0
    # 末格：「一」——横向铺满、竖向很矮，不能当残段
    img[10 + 5 * SLOT_H:10 + 6 * SLOT_H, 20:60] = 255
    img[10 + 5 * SLOT_H + 25:10 + 5 * SLOT_H + 33, 20:60] = 0
    # 中间格（第 3 格）：一个小点，不在列端，不动
    img[10 + 2 * SLOT_H:10 + 3 * SLOT_H, 20:60] = 255
    img[10 + 2 * SLOT_H + 20:10 + 2 * SLOT_H + 28, 38:46] = 0
    return img


def _kinds(**kw):
    r = RB.segment_column(_column(), period=SLOT_H, n_body_slots=N, border_top=10.0,
                          border_bottom=10.0 + SLOT_H * N, detect_jiazhu=False, seam_band=0, **kw)
    return {c.slot: c.kind for c in r.cells}


def test_off_by_default_dash_stays_char():
    assert _kinds()[1] == "char"


def test_on_blanks_only_the_end_dash():
    k = _kinds(dash_blank=(0.3, 0.25))
    assert k[1] == "blank"
    assert k[N] == "char", "「一」横向铺满，不是残段"
    assert k[3] == "char", "中间格的小点不动"
    assert k[2] == k[4] == k[5] == "char"
