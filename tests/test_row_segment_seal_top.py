"""去印点列列顶印边残块抹白（row_segment._clear_seal_top_residue，史記卷首页 02 p2 c4、10 p2 c6）。"""
import numpy as np

from open_guji_cv.steps.row_segment import _clear_seal_top_residue


class _Map:
    """列图坐标原样当页坐标（列顶贴印上边）。"""
    def to_page_tr(self, x, y):
        return x, y


SEAL = [(0.0, 0.0, 400.0, 1600.0, None)]   # 印上边 y=0，边带 0.08×1600=128


def _col(w=200, h=1000):
    return np.full((h, w), 255, np.uint8)


def _char(img, y0, y1, x0=40, x1=160):
    img[y0:y1, x0:x1:7] = 0          # 竖笔散开横跨整个字宽
    img[y0:y1:9, x0:x1] = 0


def test_isolated_blob_at_seal_top_cleared():
    img = _col()
    _char(img, 20, 140)                # 印上边框的印泥块：矮、与下面隔开
    _char(img, 260, 400)
    out = _clear_seal_top_residue(img, _Map(), SEAL)
    assert (out[20:140] == 255).all() and (out[260:400] == img[260:400]).all()


def test_edge_line_cleared():
    img = _col()
    img[10:240, 185:195] = 0           # 贴列边的界行残线，与首字只隔 30 行
    _char(img, 270, 400)
    out = _clear_seal_top_residue(img, _Map(), SEAL)
    assert (out[10:240] == 255).all() and (out[270:400] == img[270:400]).all()


def test_title_char_touching_next_kept():
    img = _col()
    _char(img, 10, 150)                # 题列首字贴着下一字
    _char(img, 155, 300)
    assert (_clear_seal_top_residue(img, _Map(), SEAL) == img).all()


def test_no_seal_or_outside_rim_kept():
    img = _col()
    _char(img, 300, 420)
    _char(img, 700, 820)
    assert (_clear_seal_top_residue(img, _Map(), SEAL) == img).all()
    assert (_clear_seal_top_residue(img, _Map(), []) == img).all()
