"""row_segment 书级开关 roster_seal_despeckle：大印压着的卷端标题列去印点后重切（史記 p2）。"""
from types import SimpleNamespace

import numpy as np

from open_guji_cv.steps.row_segment import (RowSegmentParams, _despeckle, _despeckled_ok, _ref_count,
                                            _seal_rim_residue)


def _it(x0, y0, x1, y1):
    return SimpleNamespace(x0=x0, y0=y0, x1=x1, y1=y1)


class _Id:
    def to_page_tr(self, x, y):
        return x, y


def test_off_by_default_not_in_params_dump():
    assert RowSegmentParams().roster_seal_despeckle == 0
    assert "roster_seal_despeckle" not in RowSegmentParams().model_dump()
    assert RowSegmentParams(roster_seal_despeckle=6).model_dump()["roster_seal_despeckle"] == 6


def test_ref_count():
    assert _ref_count("漢太史令 司馬遷撰") == 8
    assert _ref_count(None) == -1
    assert _ref_count("史<note>記</note>") == -1


def test_despeckle_keeps_strokes_drops_dots():
    img = np.full((200, 60), 255, np.uint8)
    img[20:120, 25:35] = 0                     # 一笔竖
    for y, x in [(150, 5), (170, 50), (185, 20)]:
        img[y:y + 3, x:x + 3] = 0              # 印泥点
    out = _despeckle(img, 6)
    assert (out[20:120, 25:35] < 128).mean() > 0.9
    assert (out[140:200] < 128).sum() == 0


def test_despeckled_ok_rejects_dot_cell_but_accepts_yi():
    img = np.full((300, 60), 255, np.uint8)
    img[10:50, 10:50] = 0                      # 字
    img[60:100, 10:50] = 0                     # 字
    img[128:132, 5:55] = 0                     # 「一」：墨少但宽
    items = [_it(0, 0, 60, 55), _it(0, 55, 60, 105), _it(0, 110, 60, 150)]
    assert _despeckled_ok(items, img)
    img[200:203, 28:31] = 0                    # 只有一点残墨的格
    assert not _despeckled_ok(items + [_it(0, 190, 60, 230)], img)


def test_seal_rim_residue_only_end_cell_at_seal_edge_with_little_ink():
    img = np.full((1000, 60), 255, np.uint8)
    seal = [0, 100, 60, 900]
    items = []
    for k, y in enumerate(range(100, 900, 100)):
        img[y + 20:y + 80, 15:45] = 0
        items.append(_it(0, y, 60, y + 100))
    assert not _seal_rim_residue(items, img, _Id(), [seal])
    img[100:200] = 255
    img[105:120, 10:30] = 0                    # 首格只剩印上边的残点
    assert _seal_rim_residue(items, img, _Id(), [seal])
    assert not _seal_rim_residue(items, img, None, [seal])
    assert not _seal_rim_residue(items, img, _Id(), [])


def test_trim_low_ink_drops_only_faint_extras():
    from open_guji_cv.steps.row_segment import _trim_low_ink
    img = np.full((600, 60), 255, np.uint8)
    items = []
    for k, y in enumerate(range(0, 600, 100)):
        if k == 2:
            img[y + 40:y + 44, 28:32] = 0          # 残点格
        else:
            img[y + 20:y + 80, 15:45] = 0
        items.append(_it(0, y, 60, y + 100))
    out = _trim_low_ink(items, img, 1)
    assert out is not None and len(out) == 5 and items[2] not in out
    assert _trim_low_ink(items, img, 2) is None   # 第二少的格墨足，不动
    assert "roster_seal_trim_extra" not in RowSegmentParams().model_dump()
