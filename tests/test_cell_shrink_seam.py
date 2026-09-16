"""cell_shrink._apply_seam：紧框裁片按折线缝抹白邻格像素，再收紧到剩余墨迹。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.steps.cell_shrink import _apply_seam


def _img():
    """列图 100×60：本字主体 30..60 行（x 10..50），上邻字一笔从 20 行拖到 34 行（x 12..16），
    本字上探一笔 24..30 行（x 40..46）。缝在 x 12..16 处走 35（把拖笔留给上格），
    在 x 40..46 处走 22（从上探笔上方绕过），其余走 27。"""
    img = np.full((100, 60), 255, np.uint8)
    img[30:60, 10:50] = 0
    img[20:35, 12:17] = 0          # 上邻字拖下来的笔
    img[24:30, 40:47] = 0          # 本字上探的笔
    seam = np.full(60, 27, dtype=int)
    seam[12:17] = 35
    seam[40:47] = 22
    return img, seam


def test_apply_seam_removes_neighbour_stroke_and_keeps_own_probe():
    img, seam = _img()
    bbox = (10.0, 20.0, 50.0, 60.0)              # extractor 给的紧框，把拖笔也框进来了
    patch = img[20:60, 10:50]
    out, nb = _apply_seam(img, patch, bbox, seam_top=seam, seam_bottom=None, cell_x0=0.0)
    # 拖笔（20..34 行，x 12..16）被抹白；上探笔（24..30，x 40..46）保留
    x0, y0, x1, y1 = (int(v) for v in nb)
    assert y0 == 24 and y1 == 60 and x0 == 10 and x1 == 50, nb
    assert not (out[:35 - y0, 12 - x0:17 - x0] < 128).any()
    assert (out[24 - y0:30 - y0, 40 - x0:47 - x0] < 128).all()


def test_apply_seam_bottom_side_and_bbox_shrinks():
    img, seam = _img()
    # 把同一张图当"上格"：缝之下（≥ seam）的像素属下格 → 本字主体全部抹掉，只剩 20..35 的拖笔
    bbox = (10.0, 20.0, 50.0, 60.0)
    out, nb = _apply_seam(img, img[20:60, 10:50], bbox, seam_top=None, seam_bottom=seam, cell_x0=0.0)
    x0, y0, x1, y1 = (int(v) for v in nb)
    assert y0 == 20 and y1 == 35 and x0 == 12 and x1 == 17, nb
    assert (out < 128).sum() == 15 * 5


def test_apply_seam_without_ink_left_returns_unchanged_bbox():
    img = np.full((50, 30), 255, np.uint8)
    img[10:20, 5:25] = 0
    seam = np.full(30, 25, dtype=int)             # 缝在墨之下：下格裁片抹白后什么都不剩
    bbox = (5.0, 10.0, 25.0, 20.0)
    out, nb = _apply_seam(img, img[10:20, 5:25], bbox, seam_top=seam, seam_bottom=None, cell_x0=0.0)
    assert nb == bbox and not (out < 128).any()
