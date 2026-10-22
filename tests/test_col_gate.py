"""R6 整页／整列丢字检查（GUJI-661）：自造页图与 Step3 产物，不碰真书。"""
from __future__ import annotations

import cv2
import numpy as np

from open_guji_cv.ops.col_gate import check_page

W, H, PERIOD, CW = 1000, 900, 100, 160
XS = [200, 400, 600]                    # 三列的图上左缘


def _glyph(img, x, y, w=110, h=90):
    """画一个「字」：框＋十字笔画，填充率与连通性像真字。"""
    cv2.rectangle(img, (x, y), (x + w, y + h), 0, 12)
    cv2.line(img, (x + w // 2, y), (x + w // 2, y + h), 0, 12)
    cv2.line(img, (x, y + h // 2), (x + w, y + h // 2), 0, 12)


def _page(skip=None):
    img = np.full((H, W), 255, np.uint8)
    for ci, x0 in enumerate(XS):
        for s in range(6):
            if skip != (ci, s):
                _glyph(img, x0 + 25, 100 + s * PERIOD + 5)
    return img


def _step3(cols=(0, 1, 2), blank=()):
    """`quad_page` 横向镜像：x_page = W − x_img。"""
    out = []
    for ci in cols:
        x0, x1 = XS[ci], XS[ci] + CW
        cells = []
        for s in range(6):
            y0, y1 = 100 + s * PERIOD, 100 + (s + 1) * PERIOD
            cells.append({"kind": "blank" if (ci, s) in blank else "char", "slot": s + 1,
                          "quad_page": [[W - x1, y0], [W - x0, y0], [W - x0, y1], [W - x1, y1]]})
        out.append({"col": ci + 1, "cells": cells})
    return {"columns": out, "period": PERIOD}


def _kinds(fs):
    return sorted((f.kind, f.col) for f in fs)


def test_clean_page_reports_nothing():
    assert check_page(_page(), 1, _step3()) == []


def test_blank_cell_over_ink_is_dropped():
    fs = check_page(_page(), 1, _step3(blank={(1, 2)}))
    assert _kinds(fs) == [("dropped", 2)]


def test_cell_over_empty_paper_is_fine():
    assert check_page(_page(skip=(1, 2)), 1, _step3(blank={(1, 2)})) == []


def test_missing_column_found():
    fs = check_page(_page(), 1, _step3(cols=(0, 2)))
    assert [f.kind for f in fs] == ["col_missing"]
    assert 400 <= fs[0].detail["x0"] <= 460


def test_stain_and_frame_bar_are_not_characters():
    img = _page(skip=(1, 2))
    rng = np.random.default_rng(0)
    patch = img[400:490, 425:515]
    patch[rng.random(patch.shape) < 0.12] = 0                                            # 污渍碎点
    cv2.rectangle(img, (425, 410), (535, 450), 0, -1)                                    # 版框折角的粗黑块
    assert check_page(img, 1, _step3(blank={(1, 2)})) == []
