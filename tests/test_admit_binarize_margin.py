"""人裁刻例进库的二值化不能带整页的纸缘留白（2026-09-19）。

`binarize_page` 自 2026-09-17 起最外 20px 强制判纸（挡扫描纸缘渐变），字块只有 64×88
上下，套上去四边笔画全没：09-18/19 入库的 405 条人裁刻例自身相似度中位 0.43，
人裁 7 次的「宐」候选里根本不出现。这里钉两件事：整页函数在字块尺寸上确实会啃边
（免得将来有人觉得「这条测试没必要」），以及进库用的调用方式不啃。
"""

from __future__ import annotations

import numpy as np

from open_guji_cv.utils.binarized import binarize_page


def _patch(h: int = 64, w: int = 88) -> np.ndarray:
    """一个「口」形的字块：笔画贴着四边 6px 处，正是纸缘留白会啃掉的位置。"""
    p = np.full((h, w), 235, np.uint8)
    p[6:12, 6:w - 6] = 20
    p[h - 12:h - 6, 6:w - 6] = 20
    p[6:h - 6, 6:12] = 20
    p[6:h - 6, w - 12:w - 6] = 20
    return p


def test_page_binarizer_default_eats_patch_edges():
    out = binarize_page(_patch())
    assert (out[6:12, 20:60] == 255).all(), "整页缺省的纸缘留白该把贴边的横抹掉——这条不成立说明前提变了"


def test_patch_binarize_without_edge_margin_keeps_strokes():
    out = binarize_page(_patch(), edge_margin=0)
    assert (out[6:12, 20:60] == 0).all()
    assert (out[52:58, 20:60] == 0).all()
    assert (out[20:44, 6:12] == 0).all()


def test_consumer_uses_no_edge_margin():
    """进库那一行必须显式 edge_margin=0——按源码钉，避免下次有人改回去。"""
    import inspect
    from open_guji_cv.feedback import consumers
    src = inspect.getsource(consumers.glyphdb_admit)
    assert "binarize_page(img, edge_margin=0)" in src
