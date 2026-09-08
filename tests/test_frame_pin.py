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


def _col(bars: list[tuple[int, int]], strokes: list[tuple[int, int, int, int]],
         w: int = 200, h: int = 260):
    """列图：bars 是横贯整幅宽的版框线行段 (起, 止)；strokes 是只在
    文字带内的字笔画 (起, 止, x0, x1)。"""
    img = np.full((h, w), 255, np.uint8)
    for a, b in bars:
        img[a:b, :] = 0
    for a, b, xa, xb in strokes:
        img[a:b, xa:xb] = 0
    return img


def test_thick_frame_bar_alone_is_not_char_ink():
    """5~8px 厚的版框线本身满足「连续多行、行墨够」，但它带外还在走——
    不算字墨。算了字墨桩就永远钉不下去，末格整条框线进裁片（用户实审 30 例）。"""
    img = _col([(30, 38)], [])
    assert not _has_char_ink(img, 20, 180, 10, 50)


def test_char_stroke_beside_the_bar_still_counts():
    """框线之上还有一段真字墨（带内 0.3 宽、10 行、带外无墨）→ 仍是字墨，不钉。"""
    img = _col([(40, 47)], [(20, 30, 60, 110)])
    assert _has_char_ink(img, 20, 180, 10, 50)


def test_wide_stroke_without_outside_ink_is_char():
    """「二」的底横、「一」：带内行墨 ≥0.5，但到界行就停、带外无墨 → 是字。"""
    img = _col([], [(20, 28, 25, 175)])
    assert _has_char_ink(img, 20, 180, 10, 50)


def test_no_probe_falls_back_to_dense_rule():
    """探测窗取不到（条带贴满图宽）时只认第一档：满宽的密行是框线，三成宽的不是。"""
    img = np.full((260, 180), 255, np.uint8)
    img[30:38, :] = 0
    assert not _has_char_ink(img, 0, 180, 10, 50)
    img2 = np.full((260, 180), 255, np.uint8)
    img2[20:40, :54] = 0
    assert _has_char_ink(img2, 0, 180, 10, 50)


def test_column_image_thin_margin_uses_dense_rule():
    """v2 列图：内容窗口外只剩 5px 边距、框线到窗口就停（带外墨 0）。探不到
    就只认密行——满宽 0.9 的框线行不算字墨，桩要钉得下去（vol01 p11 c3 实况）。"""
    img = np.full((260, 190), 255, np.uint8)
    img[30:38, 5:185] = 0
    assert not _has_char_ink(img, 5, 185, 10, 50)
    img[15:25, 60:110] = 0          # 框线上方再来一段真字墨 → 仍算字
    assert _has_char_ink(img, 5, 185, 10, 50)


# ── 2026-09-08：列图上「字的顶横被当成上框线」──────────────────────
# measure_row_frames 是整页尺子（字最长横段 ≤0.1 页宽）；喂它一字宽的列图，
# 「可/不/南/要/因」的顶横行墨 0.55~0.62 就成了顶端搜索窗里的第一条「框线」。
# 两册前 50 页普查：真框线与顶边之间连续空白 ≤28 行，被误认的顶横上方空白
# 119~156 行（整整一个空格）；「南」的顶横上方还连着自己的竖笔。


def _col_top(bars: list[tuple[int, int]], strokes: list[tuple[int, int, int, int]],
             w: int = 180, h: int = 2400):
    """列图（与真列图同高，框线搜索窗按图高比例算）。"""
    img = np.full((h, w), 255, np.uint8)
    for a, b in bars:
        img[a:b, :] = 0
    for y0, y1, x0, x1 in strokes:
        img[y0:y1, x0:x1] = 0
    return img


def test_top_stroke_after_a_blank_slot_is_not_a_frame():
    """第 1 格空白、第 2 格「可」的顶横（宽 0.6 列宽）不是框线：不钉桩。"""
    from open_guji_cv.clustering.extractor import frame_band_inner
    img = _col_top([], [(140, 146, 36, 144), (150, 230, 60, 120)])
    top, _ = frame_band_inner(img, blank_max=0.35 * 116)
    assert top == 0, f"顶横被当成框线钉在 {top}"
    top_old, _ = frame_band_inner(img)            # 不传 blank_max = 老口径
    assert top_old == 146, "对照：老口径确实会把顶横当框线"


def test_real_frame_at_the_very_top_is_still_pinned():
    """真框线：贴着列图顶边（前面至多二三十行空白），照钉。"""
    from open_guji_cv.clustering.extractor import frame_band_inner
    img = _col_top([(20, 30)], [(60, 150, 60, 120)])
    top, _ = frame_band_inner(img, blank_max=0.35 * 116)
    assert top == 30


def test_stroke_with_ink_attached_above_is_not_a_frame():
    """「南」：顶横上方连着十字竖笔——框线之上不会挂着墨，不钉。"""
    from open_guji_cv.clustering.extractor import frame_band_inner
    img = _col_top([], [(8, 40, 86, 94), (34, 42, 36, 144), (46, 130, 50, 130)])
    top, _ = frame_band_inner(img, blank_max=0.35 * 112)
    assert top == 0, f"南的顶横被当成框线钉在 {top}"


def test_frame_touched_from_below_is_still_pinned():
    """框线被下面的字顶住（p48「御」）不算「上方连墨」，照钉。"""
    from open_guji_cv.clustering.extractor import frame_band_inner
    img = _col_top([(3, 15)], [(15, 120, 70, 110)])
    top, _ = frame_band_inner(img, blank_max=0.35 * 116)
    assert top == 15


def test_hinted_pin_finds_the_frame_next_to_the_hint_not_the_stroke():
    """v2 给了 border_bottom 提示：从提示向外找最近的框线行；「至」的底横离提示 44px、
    真下框离提示 4px，认下框。"""
    from open_guji_cv.clustering.extractor import frame_band_inner
    img = _col_top([(2385, 2392)], [(2333, 2345, 36, 144), (2250, 2330, 60, 120)])
    top, bot = frame_band_inner(img, blank_max=0.35 * 116, top_hint=0.0, bottom_hint=2389.0)
    assert bot == 2385, f"下框内缘 {bot}"
    assert top == 0


def test_hinted_pin_gives_up_when_no_bar_near_hint():
    """提示附近没有框线行（vol01/151 型偏差超过容差、或框根本不在图里）：检不出，不钉。"""
    from open_guji_cv.clustering.extractor import frame_band_inner
    img = _col_top([], [(2250, 2330, 60, 120)])
    top, bot = frame_band_inner(img, blank_max=0.35 * 116, top_hint=0.0, bottom_hint=2389.0)
    assert (top, bot) == (0, img.shape[0])


def test_faint_frame_rows_are_frame_when_trusted():
    """trust_frame：带内 0.35 墨、长横段的行是淡框线，不是字墨（vol02/81「因」）。"""
    img = _page([(20, 26, 0.36)])          # 一段 0.36 墨率的连续横条
    assert _has_char_ink(img, 0, 180, 10, 50)                    # 老口径：无探测窗只认密行 → 当字墨
    assert not _has_char_ink(img, 0, 180, 10, 50, trust_frame=True)
