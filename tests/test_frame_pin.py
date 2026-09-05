"""版框带内缘钉桩的字墨闸回归。

## 这个 bug 长什么样

钉桩把图块条带的上界钉在版框带内缘，防止框墨进条带。原先只有一条**比例闸**
（最多吃掉 0.35 × 格高），它只问「吃掉几分之几」，不问「吃掉的是不是字」。

实测 vol01 十个页面的首个正文格：桩落在 y=143~150，而字墨从 y≈123 就开始，
差 32~39px 恰好卡在 40px 限额之下 → 每次都钉，每次都把「非」「簡」这类字的
顶横整条切掉。用户在 10 个不同页面反复标 slot 2 截断，33 条切分缺陷里
**17 条压在这一格**。

修法是补一条**直接看墨**的闸：桩要跨过的那段里若已有成段字墨就不钉。
本模块的红线本来就是「宁可留框渣，绝不吞字」。

## 为什么它躲过了 R4 尺子

R4 只量「紧贴紧框的墨」，而这里被切掉的墨与紧框之间隔着空白（顶横与字身
之间本就有距离），量法够不着。修复后 R4 从 0.51% 降到 0.05% —— 说明它
**部分**能测到，但远不是全部。缺陷聚集（人裁标注按格位聚）才是发现它的手段。
"""

from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.clustering.extractor import (FRAME_BAND_MAX_CUT,
                                               PIN_INK_ROW_T, PIN_INK_RUN,
                                               _has_char_ink)


def _page(rows: list[tuple[int, int, float]], w: int = 180, h: int = 260):
    """按 (起, 止, 墨率) 造一张灰度图。"""
    img = np.full((h, w), 255, np.uint8)
    for a, b, r in rows:
        n = int(w * r)
        img[a:b, :n] = 0
    return img


def test_char_ink_detected():
    """成段字墨（连续多行、墨率够）必须认出来——认不出就会被钉桩切掉。"""
    img = _page([(20, 40, 0.30)])
    assert _has_char_ink(img, 0, 180, 10, 50)


def test_thin_frame_residue_not_char_ink():
    """框渣是薄的、断续的——不能当成字墨，否则桩永远不钉、框墨全进来。"""
    img = _page([(20, 22, 0.30), (30, 31, 0.25)])
    assert not _has_char_ink(img, 0, 180, 10, 50)


def test_faint_rows_not_char_ink():
    """墨率不够的行不算——扫描噪点常连成一片但很淡。"""
    img = _page([(20, 40, 0.05)])
    assert not _has_char_ink(img, 0, 180, 10, 50)


def test_empty_band_is_safe():
    assert not _has_char_ink(_page([]), 0, 180, 10, 50)
    assert not _has_char_ink(_page([]), 0, 180, 50, 10)   # 反向区间
    assert not _has_char_ink(_page([]), 0, 0, 10, 50)     # 空宽度


def test_thresholds_are_sane():
    """闸值本身的护栏：放太松则框墨进来，放太紧则继续切字。"""
    assert 0 < PIN_INK_ROW_T < 0.5, "行墨率闸离谱"
    assert 2 <= PIN_INK_RUN <= 8, "连续行数闸离谱"
    assert 0 < FRAME_BAND_MAX_CUT < 0.5


@pytest.mark.parametrize("page,col,slot", [
    (26, 3, 2), (33, 3, 2), (11, 1, 2), (20, 3, 2), (22, 9, 2),
])
def test_real_pages_no_longer_clip_slot2(page, col, slot):
    """真数据：这些格位曾被人裁标 truncated，修复后紧框外不该再有成段字墨。"""
    import cv2

    from open_guji_cv.core.step import page_key
    from open_guji_cv.products import kinds as _kinds  # noqa: F401
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    st = ProductStore()
    cells = st.read("vol01", "row_segment", page_key(page), "cells")
    ci = st.read("vol01", "cell_shrink", page_key(page), "char_index")
    if cells is None or ci is None:
        pytest.skip("没有产物")
    cc = [x for x in cells.columns if x.col == col]
    cic = [x for x in ci.columns if x.col == col]
    if not cc or not cic:
        pytest.skip("没有该列")
    cell = [x for x in cc[0].cells if x.slot == slot]
    ch = [x for x in cic[0].chars if getattr(x, "slot", None) == slot]
    if not cell or not ch:
        pytest.skip("没有该格")
    p = ImageCache().get("vol01", "column_image", f"p{page:04d}c{col:02d}")
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p else None
    if img is None:
        pytest.skip("没有列图")
    above = (img < 128)[int(cell[0].y0):int(ch[0].bbox_col[1])]
    if above.size == 0:
        return
    rows = above.mean(axis=1) > 0.05
    run = best = 0
    for v in rows:
        run = run + 1 if v else 0
        best = max(best, run)
    assert best < 6, f"p{page}c{col}s{slot} 紧框上方仍有 {best} 行成段字墨（又切字顶了）"
