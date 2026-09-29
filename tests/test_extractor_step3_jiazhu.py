# -*- coding: utf-8 -*-
"""Step4 extractor 按 Step3 补拆雙行夹注（overview#266）。

extractor 自己那套 v1 夹注判据的缝对齐容差是 8px；「內府藏本」「山東巡撫採進本」这类
提要末尾的版本小注只有 2~3 行、缝漂移到 15px，Step3（`jiazhu_split.ALIGN_PAIR`=16）认得、
extractor 认不得，于是整格发成一个满宽「字」。v2 调用方把 Step3 的缝传进来，extractor
只给自己没认的格补拆。合成列图按 vol03 几何画：列宽 180、字距 115，小字 ~60px。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.clustering.extractor import CharExtractor

W, P = 180, 115.0


def _column():
    img = np.full((6 * int(P) + 40, W), 255, np.uint8)
    # 前两格正文（居中，0.6 列宽）
    for k in range(2):
        y = 20 + k * int(P)
        img[y + 20:y + 28, 36:144] = 0
        img[y + 10:y + 100, 86:94] = 0
    # 第 3、4 格：两行小注，左右各一个小字；两行的缝差 15px（>8 过不了 v1 的对齐）
    for k, seam in ((2, 84), (3, 99)):
        y = 20 + k * int(P)
        for x0, x1 in ((6, seam - 6), (seam + 6, W - 6)):
            img[y + 20:y + 26, x0:x1] = 0            # 横
            img[y + 20:y + 95, (x0 + x1) // 2 - 3:(x0 + x1) // 2 + 3] = 0   # 竖
            img[y + 60:y + 66, x0 + 5:x1 - 5] = 0
    return img


def _grid(with_step3: bool):
    cells = []
    for k in range(5):
        c = {"type": "char" if k < 4 else "empty", "index": k, "y_top": 20 + k * P,
             "y_bottom": 20 + (k + 1) * P, "is_punct": False, "seam_top": None, "seam_bottom": None}
        if with_step3 and k in (2, 3):
            c.update(jiazhu_cx={2: 84.0, 3: 99.0}[k], jiazhu_tail_a=False)
        cells.append(c)
    return {"image_size": [W, 6 * int(P) + 40], "chars_per_line": 5,
            "grid": {"shear": 0.0, "period": float(W), "cell_h": P, "head_raise_rows": 0,
                     "frame_top": None, "frame_bottom": None, "frame_bar_strategy": "side_gap"},
            "columns": [{"index": 1, "left_x": 0.0, "right_x": float(W),
                         "cell_left_x": 0.0, "cell_right_x": float(W), "cells": cells}]}


def _subs(res):
    out = {}
    for inst, _p in res:
        out.setdefault(int(inst.idx), set()).add(inst.sub)
    return out


def test_without_step3_hint_the_drifting_note_stays_whole():
    subs = _subs(CharExtractor().extract_page(_column(), _grid(False), "t", "1"))
    assert subs[2] == {None} and subs[3] == {None}     # 旧行为：整格一个「字」


def test_step3_hint_splits_the_note_into_a_and_b():
    res = CharExtractor().extract_page(_column(), _grid(True), "t", "1")
    subs = _subs(res)
    assert subs[2] == {"a", "b"} and subs[3] == {"a", "b"}
    assert subs[0] == {None} and subs[1] == {None}      # 正文格不动
    for inst, _p in res:
        if inst.sub:
            assert "jiazhu" in inst.flags and "wide_gap" not in inst.flags
    # a 是右子列：x 起点在缝右
    a3 = next(i for i, _ in res if int(i.idx) == 3 and i.sub == "a")
    assert a3.bbox[0] >= 99 - 2
