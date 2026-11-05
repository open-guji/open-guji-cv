"""extractor.is_ink_blob（cell_shrink.ink_blob_empty，全唐文 S6 墨团当字，2026-11-05）。"""
import cv2
import numpy as np

from open_guji_cv.clustering.extractor import is_ink_blob
from open_guji_cv.steps.cell_shrink import CellShrinkParams

CELL_H = 210.0


def test_solid_blob_is_blob():
    p = np.full((92, 91), 255, np.uint8)
    cv2.ellipse(p, (45, 46), (40, 42), 0, 0, 360, 0, -1)
    p[::3, ::4] = 255                      # 灰墨团二值后带麻点（011:68:1:14），闭运算补上
    assert is_ink_blob(p, CELL_H)


def test_strokes_are_not_blob():
    one = np.full((40, 200), 255, np.uint8)
    one[10:32, 5:195] = 0                  # 「一」：扁，长短边比过限
    ten = np.full((200, 200), 255, np.uint8)
    ten[90:115, 10:190] = 0
    ten[10:190, 88:113] = 0                # 「十」：笔画粗 25，内切圆只到长边的 0.06
    dot = np.full((60, 50), 255, np.uint8)
    cv2.ellipse(dot, (25, 30), (12, 26), 20, 0, 360, 0, -1)   # 「心」的一点：细长，半径不够
    for p in (one, ten, dot):
        assert not is_ink_blob(p, CELL_H)


def test_big_solid_block_left_to_other_gates():
    p = np.full((180, 180), 255, np.uint8)
    p[5:175, 5:175] = 0                    # 长边 > 0.6 格高：整字大小的实心块不在这儿判
    assert not is_ink_blob(p, CELL_H)


def test_switch_off_not_in_dump():
    assert "ink_blob_empty" not in CellShrinkParams().model_dump()
    assert CellShrinkParams(ink_blob_empty=True).model_dump()["ink_blob_empty"] is True
