"""extractor.is_end_cell_junk 的 one_abs 逃生口（cell_shrink.tail_one_abs，全唐文列端「一」，2026-11-05）。"""
import numpy as np

from open_guji_cv.clustering.extractor import is_end_cell_junk

W, H, CELL_H = 340, 250, 240.0


def _cell(x0: int, x1: int, y0: int, y1: int) -> np.ndarray:
    p = np.full((H, W), 255, np.uint8)
    p[y0:y1, x0:x1] = 0
    return p


def test_centered_short_stroke_is_one_only_with_switch():
    p = _cell(75, 265, 100, 118)          # 宽 0.56 墙距、高 18px、居中：嘉慶本列尾「一」
    assert is_end_cell_junk(p, CELL_H) is True
    assert is_end_cell_junk(p, CELL_H, one_abs=True) is False


def test_frame_like_strokes_stay_junk():
    off_center = _cell(119, 301, 195, 213)  # 偏右 0.19 墙距（双边框内线残段，005:117:1:22）
    too_wide = _cell(2, 290, 215, 231)      # 宽 0.85 墙距（贴下框的内框线，006:125:2:22）
    for p in (off_center, too_wide):
        assert is_end_cell_junk(p, CELL_H, one_abs=True) is True


def test_stroke_touching_patch_edge_stays_junk():
    p = _cell(75, 265, H - 20, H - 2)
    assert is_end_cell_junk(p, CELL_H, one_abs=True) is True
