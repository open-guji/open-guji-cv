# -*- coding: utf-8 -*-
"""Step4 列端渣格闸听逐列格位表（Step3 记 `layout_char`）：表认下的字格不判渣。

列尾的「一」只有一条横，与版框横线形状上分不清（殿本 vol05–10 列尾「一」被判 tail_junk 16 列）。
合成列：两个正文字，列尾一格只有一条细横。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import CharExtractor

W, P = 180, 115.0


def _column():
    img = np.full((3 * int(P) + 40, W), 255, np.uint8)
    for k in range(2):
        y = 20 + k * int(P)
        img[y + 20:y + 28, 36:144] = 0
        img[y + 10:y + 100, 86:94] = 0
    y = 20 + 2 * int(P)
    img[y + 50:y + 60, 40:140] = 0                # 列尾：「一」（一横，收笔处顿一下）
    img[y + 44:y + 66, 122:142] = 0
    return img


def _grid(layout_char: bool):
    cells = [{"type": "char", "index": k, "y_top": 20 + k * P, "y_bottom": 20 + (k + 1) * P,
              "is_punct": False, "seam_top": None, "seam_bottom": None,
              **({"layout_char": True} if layout_char else {})} for k in range(3)]
    return {"image_size": [W, 3 * int(P) + 40], "chars_per_line": 3,
            "grid": {"shear": 0.0, "period": float(W), "cell_h": P, "head_raise_rows": 0,
                     "frame_top": None, "frame_bottom": None, "frame_bar_strategy": "side_gap"},
            "columns": [{"index": 1, "left_x": 0.0, "right_x": float(W),
                         "cell_left_x": 0.0, "cell_right_x": float(W), "cells": cells}]}


def _tail(res):
    return next(i for i, _p in res if int(i.idx) == 2)


def test_thin_tail_bar_is_junk_without_table():
    t = _tail(CharExtractor().extract_page(_column(), _grid(False), "t", "1"))
    assert t.cell_type == "empty" and "tail_junk" in t.flags


def test_table_confirmed_tail_char_is_kept():
    t = _tail(CharExtractor().extract_page(_column(), _grid(True), "t", "1"))
    assert t.cell_type == "char" and "tail_junk" not in t.flags


def test_table_confirmed_blank_paper_is_still_empty():
    img = _column()
    img[20 + 2 * int(P):] = 255                  # 列尾一格白纸
    t = _tail(CharExtractor().extract_page(img, _grid(True), "t", "1"))
    assert t.cell_type == "empty"
