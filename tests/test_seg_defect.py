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


def test_frame_residue_on_head_cell():
    """列首格最终字块上还留着断成几截的内框细线：frame_residue；同一字块没有全页线位就不判。"""
    from types import SimpleNamespace as NS

    import numpy as np

    from open_guji_cv.review.seg_defect import _frame_residue
    patch = np.full((100, 80), 255, np.uint8)
    patch[5:8, 5:35] = 0
    patch[6:9, 40:75] = 0                       # 两截、略斜
    patch[40:90, 30:50] = 0                     # 线下的字
    r = NS(bbox_col=(10.0, 20.0, 90.0, 120.0), sub=None)
    cc = NS(col=3, period=100.0, border_top=10.0, border_bottom=2000.0)
    lines = {"frame_half_lines_top": {3: [(26.5, 3.0)]}}
    assert _frame_residue(patch, r, cc, lines)
    assert _frame_residue(patch, r, cc, {}) is None
    clean = patch.copy()
    clean[:20] = 255
    assert _frame_residue(clean, r, cc, lines) is None
