"""史記 r79 ①类 `cut_glyph_line`：按连通块归属逐列画线（2026-11-17）。数据自造。"""
import cv2
import numpy as np

from open_guji_cv.impl.keben import row_boundaries as rb

P = 100.0


def _cc(ink):
    return cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)[1:3]


def _c(kind, y=None):
    return rb.SeamCandidate(kind=kind, y=y, seam_ink=0, dev_max=0)


UP = type("C", (), {"y0": 0.0})()
DN = type("C", (), {"y1": 260.0})()


def _interlock():
    """上字身 x10–40 y20–90 连一条粗捺尾（横 y80–88 x40–90，竖 x70–90 伸到 y132）；另有上字一点 x55–65 y30–40。
    下字 x10–55 y100–190，在捺尾左边、比捺尾尖高——没有整行白。直线 y95 劈开上字那块。"""
    ink = np.zeros((260, 100), bool)
    ink[20:90, 10:40] = True
    ink[80:88, 40:90] = True
    ink[80:132, 70:90] = True
    ink[30:40, 55:65] = True
    ink[100:190, 10:55] = True
    return ink


def test_glyph_line_follows_ownership():
    ink = _interlock()
    lab, st = _cc(ink)
    cands, ch, by = rb._glyph_line([_c("straight")], 0, "rule", ink, (lab, st), 95.0, P, 0.5, UP, DN)
    assert by == "glyph" and cands[ch].kind == "glyph_line"
    ys = np.asarray(cands[ch].y)
    assert not rb._split_glyphs(lab, st, ys, P)
    assert np.all(ys[10:55] <= 100) and np.all(ys[10:55] >= 90)     # 下字上面
    assert np.all(ys[70:90] >= 132)                                 # 捺尾下面
    assert cands[ch].seam_ink == 0


def test_glyph_line_off_human_and_joined():
    ink = _interlock()
    cc = _cc(ink)
    for args in ((0, "human", 0.5), (0, "rule", 0.0)):
        cands, ch, by = rb._glyph_line([_c("straight")], args[0], args[1], ink, cc, 100.0, P, args[2], UP, DN)
        assert (len(cands), ch, by) == (1, 0, args[1])
    ink2 = ink.copy()
    ink2[88:100, 55:68] = True           # 捺尾横和下字粘成一块（两字一块）：不动
    cands, ch, by = rb._glyph_line([_c("straight")], 0, "rule", ink2, _cc(ink2), 95.0, P, 0.5, UP, DN)
    assert by == "rule" and len(cands) == 1


def test_glyph_line_no_split_noop():
    ink = np.zeros((260, 100), bool)
    ink[10:90, 10:90] = True
    ink[110:190, 10:90] = True
    cands, ch, by = rb._glyph_line([_c("straight")], 0, "rule", ink, _cc(ink), 95.0, P, 0.5, UP, DN)
    assert (len(cands), by) == (1, "rule")
