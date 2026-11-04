"""review/seg_defect：切坏检测（离线、只读）的两团字判据。"""
import numpy as np

from open_guji_cv.review.seg_defect import _valley_split


def _patch(parts, h=200, w=60):
    img = np.full((h, w), 255, np.uint8)
    for y0, y1 in parts:
        img[y0:y1, 10:50] = 0
    return img


def test_two_blobs_with_gap_is_merged():
    assert _valley_split(_patch([(5, 85), (115, 195)]), 100.0)


def test_inner_gap_of_one_char_not_merged():
    # 「二」「三」：字内空行，下面那团矮于 0.3 格高
    assert _valley_split(_patch([(5, 90), (110, 125)]), 100.0) is None
    assert _valley_split(_patch([(5, 195)]), 100.0) is None
