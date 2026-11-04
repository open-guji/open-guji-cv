"""写本列首内框细线（extractor.strip_inner_frame_band）：断成几截、略斜的线按全页半格线位抹掉；
字头、只有一横的字、离线位远的横画不动（SJ r8：怨→惡、一→二、曰→白）。"""
import numpy as np

from open_guji_cv.clustering.extractor import strip_inner_frame_band

W, H, CH = 180, 150, 120      # 图块宽高、格高
LY = ((22.0, 5.0),)           # 全页半格线位（图块坐标，线厚）


def _char(p):
    p[45:130, 85:95] = 0      # 一竖
    p[80:86, 40:140] = 0      # 一横
    return p


def _broken_line(p, y=18):
    p[y:y + 6, 10:60] = 0     # 三截，不到 0.85 窗宽，略有高低
    p[y + 1:y + 7, 70:130] = 0
    p[y + 2:y + 6, 140:155] = 0
    return p


def test_broken_line_removed_char_kept():
    p = _broken_line(_char(np.full((H, W), 255, np.uint8)))
    out = strip_inner_frame_band(p, CH, bottom=False, line_ys=LY)
    assert (out[:40] == 255).all()
    assert (out[40:] == p[40:]).all()


def test_no_page_line_position_kept():
    p = _broken_line(_char(np.full((H, W), 255, np.uint8)))
    assert strip_inner_frame_band(p, CH, bottom=False, line_ys=()) is p


def test_lone_stroke_without_char_below_kept():
    """线下没字：只有一横的「一」。"""
    p = _broken_line(np.full((H, W), 255, np.uint8))
    assert strip_inner_frame_band(p, CH, bottom=False, line_ys=LY) is p


def test_stroke_far_from_line_position_kept():
    """离线位超过 INNER_BAND_REACH 的横画是字的（「二」「三」的上横）。"""
    p = _char(np.full((H, W), 255, np.uint8))
    p[45:51, 30:150] = 0
    assert strip_inner_frame_band(p, CH, bottom=False, line_ys=LY) is p


def test_char_head_touching_line_kept():
    """线跟字头连成一块（字头压线）：整块不在线带里，不动。"""
    p = _broken_line(_char(np.full((H, W), 255, np.uint8)))
    p[18:46, 85:95] = 0       # 竖笔顶到线上
    out = strip_inner_frame_band(p, CH, bottom=False, line_ys=LY)
    assert (out[:, 80:100] == p[:, 80:100]).all()


def test_short_dot_alone_kept():
    """线带里只有一个小点（「主」「六」的点），不够 INNER_BAND_SEG 宽，不动。"""
    p = _char(np.full((H, W), 255, np.uint8))
    p[18:24, 85:95] = 0
    assert strip_inner_frame_band(p, CH, bottom=False, line_ys=LY) is p


def test_bottom_line_for_tail_cell():
    p = _broken_line(_char(np.full((H, W), 255, np.uint8)))[::-1].copy()
    out = strip_inner_frame_band(p, CH, bottom=True, line_ys=((H - 22.0, 5.0),))
    assert (out[H - 40:] == 255).all()
    assert (out[:H - 40] == p[:H - 40]).all()
