# -*- coding: utf-8 -*-
"""雙行小注两行字数可不等（设计稿方案 A，Sheldon 2026-11-03 定；史記文淵閣本写本）。

钉住：段尾单半时短的那行按自己的字数切（`row_boundaries._free_split`）；开关缺省关、不进参数哈希。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.impl.keben.row_boundaries import _free_split
from open_guji_cv.steps.row_segment import RowSegmentParams

H, W, CX = 300, 40, 20


def _col(a_rows, b_rows):
    """ink[y, x]：a 行在右（x≥CX），b 行在左；每个字是一段 [y0, y1) 的实心墨块（边上各留 3 列白）。"""
    ink = np.zeros((H, W), dtype=bool)
    for y0, y1 in a_rows:
        ink[y0:y1, CX + 3:W - 3] = True
    for y0, y1 in b_rows:
        ink[y0:y1, 3:CX - 3] = True
    return ink


def _cuts(ink, long_sub):
    return _free_split(ink, 3, long_sub, CX, 0, H, [0.0, 100.0, 200.0, 300.0])


def test_short_row_is_cut_by_its_own_count():
    """左行写三字、右行两字（写本；整理本按右行多一字分）：右行只切两格，两字之间那条线不穿字。"""
    ink = _col(a_rows=[(15, 120), (165, 270)], b_rows=[(10, 90), (110, 190), (210, 290)])
    cuts = _cuts(ink, "b")
    assert len(cuts["b"]) == 4 and len(cuts["a"]) == 3
    assert 120 <= cuts["a"][1] <= 165
    assert 270 <= cuts["a"][-1] < H              # 末格停在自己的墨下，不补到段底


def test_stroke_poking_up_from_below_does_not_stretch_short_row():
    """段下正文字的上半探进段尾格（02:13:7「置」）：短行两字仍各一格，不被拉到段底。"""
    ink = _col(a_rows=[(10, 90), (110, 190), (210, 290)], b_rows=[(10, 90), (110, 190), (280, 300)])
    cuts = _cuts(ink, "a")
    assert 90 <= cuts["b"][1] <= 110


def test_switches_default_off_and_out_of_hash():
    assert "jiazhu_free_split" not in RowSegmentParams().model_dump()
    assert RowSegmentParams(jiazhu_rows=True, jiazhu_free_split=True).model_dump()["jiazhu_free_split"] is True


def test_rows_two_apart_fall_back():
    """两行差 2 字（右行 1 字、左行 3 字）：短行切 2 格仍空一格 → 不按本法切（SJ r6 02:58:8 段中间剩单半格）。"""
    ink = _col(a_rows=[(10, 90)], b_rows=[(10, 90), (110, 190), (210, 290)])
    assert _cuts(ink, "b") is None
