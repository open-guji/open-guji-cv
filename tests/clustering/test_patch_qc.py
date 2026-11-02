"""patch_qc.edge_frame_lines：图块上/下边残留框线的判别。"""
import numpy as np

from open_guji_cv.clustering.patch_qc import edge_bands, edge_frame_lines, has_edge_frame_line


def _blank(h=120, w=100):
    return np.full((h, w), 255, np.uint8)


def _char(p, y0=30, y1=110, x0=25, x1=75):
    """字身：一个竖画加一个横画，墨在 [y0,y1)×[x0,x1)。"""
    p[y0:y1, 47:53] = 0
    p[(y0 + y1) // 2:(y0 + y1) // 2 + 6, x0:x1] = 0
    return p


def test_top_frame_line_separated_by_gap():
    p = _char(_blank())
    p[2:8, 5:95] = 0                       # 顶上一道细框线，与字身隔 22 行
    lines = edge_frame_lines(p)
    assert [b.side for b in lines] == ["top"]
    assert has_edge_frame_line(p)


def test_bottom_frame_line():
    p = _char(_blank(), y0=5, y1=95)
    p[112:117, 3:97] = 0
    assert [b.side for b in edge_frame_lines(p)] == ["bottom"]


def test_clean_char_has_no_line():
    assert edge_frame_lines(_char(_blank())) == []
    assert edge_frame_lines(_blank()) == []


def test_char_top_stroke_close_to_body_is_not_line():
    # 「三」「王」式：上横宽扁，但紧贴字身（空白 4 行 < 0.09×120）
    p = _char(_blank(), y0=30, y1=110)
    p[20:26, 25:75] = 0
    b = edge_bands(p)["top"]
    assert b is not None and not b.is_frame_line


def test_wide_thin_line_close_to_body_counts():
    # 「帝」「初」式：框线离字近，但比字身宽得多且很薄
    p = _char(_blank(), y0=20, y1=110, x0=35, x1=65)
    p[8:13, 2:98] = 0
    assert [b.side for b in edge_frame_lines(p)] == ["top"]


def test_small_speck_is_not_line():
    p = _char(_blank())
    p[3:6, 40:46] = 0                      # 小墨点：太窄
    assert edge_frame_lines(p) == []


def test_bgr_input():
    p = _char(_blank())
    p[2:8, 5:95] = 0
    assert has_edge_frame_line(np.dstack([p, p, p]))
