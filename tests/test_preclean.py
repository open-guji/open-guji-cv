"""Step0 预清理：默认不动图，登记过的页才抹污渍，且不碰磁盘原图。"""
import numpy as np
import pytest

from open_guji_cv.utils.preclean import apply_preclean, remove_horizontal_bar


def _page_with_bar():
    """造一页：白底 + 几根竖笔 + 一条横贯的粗黑污渍条。"""
    g = np.full((300, 400), 255, np.uint8)
    for x in (60, 140, 220, 300):          # 竖笔，穿过污渍条
        g[40:260, x:x + 6] = 0
    g[120:150, 30:380] = 0                 # 污渍条
    return g


def test_bar_removed_strokes_kept():
    g = _page_with_bar()
    out = remove_horizontal_bar(g, 100, 170, min_run=40, max_stroke_w=20, min_thick=10)

    bar = out[120:150]
    assert (bar < 128).mean() < 0.10, "污渍条该基本抹干净"
    for x in (60, 140, 220, 300):          # 竖笔在条内仍连着
        assert (out[120:150, x:x + 6] < 128).any(), f"x={x} 的竖笔被误抹"
    assert (out[40:110] == g[40:110]).all(), "条以外不该动"
    assert set(np.unique(out)) <= {0, 255}, "仍是二值图"


def test_input_not_mutated():
    g = _page_with_bar()
    before = g.copy()
    remove_horizontal_bar(g, 100, 170)
    assert (g == before).all(), "入参不能被改"


def test_apply_preclean_reports_and_rejects_unknown():
    g = _page_with_bar()
    out, notes = apply_preclean(g, [{"kind": "horizontal_bar", "y0": 100, "y1": 170,
                                     "min_run": 40, "max_stroke_w": 20, "min_thick": 10}])
    assert len(notes) == 1 and "horizontal_bar" in notes[0]
    assert (out < 128).sum() < (g < 128).sum()

    with pytest.raises(ValueError, match="未知的 preclean 类型"):
        apply_preclean(g, [{"kind": "没这种"}])


def test_book_without_preclean_is_untouched():
    """没登记 preclean 的书，apply_preclean 收到空规则表就该原样返回。"""
    g = _page_with_bar()
    out, notes = apply_preclean(g, [])
    assert notes == [] and out is g
