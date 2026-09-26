# -*- coding: utf-8 -*-
"""双线版框：剥第二道 / 按 Step1 内框位置剥贴字的内框线（column_projection，2026-09-26）。"""
import numpy as np

from open_guji_cv.utils.column_projection import clean_column, column_border_trim


def _col(h=400, w=120):
    img = np.full((h, w), 255, np.uint8)
    img[:, 0:4] = 0                        # 左界行
    img[:, w - 4:] = 0                     # 右界行
    return img


def _char(img, y0, y1, x0=35, x1=85):
    img[y0:y1, x0:x0 + 8] = 0
    img[y0:y0 + 6, x0:x1] = 0
    img[y1 - 6:y1, x0:x1] = 0


def test_second_bottom_line_is_stripped_when_two_layers():
    img = _col()
    _char(img, 150, 300)
    img[340:346, 10:110] = 0               # 内框（离末字 40 行）
    img[375:390, 8:112] = 0                # 外框粗线（贴近底边）
    _, d1 = clean_column(img)
    _, d2 = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0))
    h = img.shape[0]
    assert h - d1["bottom"]["px"] > 346     # 只剥一道：内框留在图里
    assert h - d2["bottom"]["px"] <= 340    # 两道：内框也剥了
    assert h - d2["bottom"]["px"] >= 300    # 末字不碰


def test_wide_char_stroke_is_not_taken_as_second_line():
    img = _col()
    img[362:367, 40:80] = 0                # 「一」：宽 40/112，够不上 0.85，也没边距证据
    img[380:392, 8:112] = 0
    _, d = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0))
    assert img.shape[0] - d["bottom"]["px"] >= 367


def test_inner_line_touching_char_uses_step1_position():
    img = _col()
    _char(img, 200, 322)
    img[320:326, 8:112] = 0                # 内框线与末字底横粘连
    img[380:392, 8:112] = 0
    _, d = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0), inner_bottom=323.0)
    cut = img.shape[0] - d["bottom"]["px"]
    assert 314 <= cut <= 320 and d["bottom"]["case"].endswith("i")
