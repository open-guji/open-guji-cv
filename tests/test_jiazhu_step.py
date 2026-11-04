"""books/shiji_wyg/jiazhu_step：雙行小注逐步切（史記，`row_segment.jiazhu_step_split`）。自造列图。"""
import numpy as np

from open_guji_cv.books.shiji_wyg import jiazhu_step as J
from open_guji_cv.books.siku_zongmu.row_boundaries import Cell, reading_order


def _col():
    """宽 100、格高 100 的列：正文两字（1、2 格），夹注段 3 起右行 4 字、左行 5 字（小字行距 75），段下正文一字。"""
    img = np.full((800, 100), 255, np.uint8)
    for y in (10, 110):                       # 正文字：横贯缝中
        img[y:y + 80, 15:85] = 0
    for i in range(4):                        # 右行 a
        y = 205 + 75 * i
        img[y:y + 55, 58:92] = 0
    for i in range(5):                        # 左行 b
        y = 205 + 75 * i
        img[y:y + 55, 8:42] = 0
    img[590:680, 15:85] = 0                   # 段下正文
    return img


def _cells():
    """原格网：共用格线、段只给了 4 格（3–6），段下正文被算进第 7 格。"""
    cs = [Cell(slot=1, y0=0, y1=100, x0=0, x1=100, kind="char"),
          Cell(slot=2, y0=100, y1=200, x0=0, x1=100, kind="char")]
    for k, s in enumerate(range(3, 7)):
        y0 = 200 + 95 * k
        cs += [Cell(slot=s, y0=y0, y1=y0 + 95, x0=50, x1=100, kind="jiazhu_a", gap_center=50.0),
               Cell(slot=s, y0=y0, y1=y0 + 95, x0=0, x1=50, kind="jiazhu_b", gap_center=50.0)]
    cs += [Cell(slot=7, y0=580, y1=700, x0=0, x1=100, kind="char"),
           Cell(slot=8, y0=700, y1=800, x0=0, x1=100, kind="blank")]
    return cs


def test_restep_long_left_line():
    out, flags = J.restep(_cells(), _col(), (0.0, 100.0), 100.0, [(3, 4, 5)], reading_order=reading_order)
    assert out is not None, flags
    a = [c for c in out if c.kind == "jiazhu_a"]
    b = [c for c in out if c.kind == "jiazhu_b"]
    assert [c.slot for c in a] == [3, 4, 5, 6] and [c.slot for c in b] == [3, 4, 5, 6, 7]
    # 每个小字各在自己的格里
    for i, c in enumerate(b):
        assert c.y0 <= 205 + 75 * i and c.y1 >= 205 + 75 * i + 55
    main = [c for c in out if c.slot == 8]
    assert main and main[0].kind == "char" and main[0].y0 <= 590 and main[0].y1 >= 680
    assert any("jiazhu_uneven" in f for f in flags)          # 左行比右行多：分法与 ⌈N/2⌉ 不同，送审
    assert [c.order for c in reading_order(out)] == sorted(c.order for c in out)


def test_restep_falls_back_when_counts_disagree():
    # 整理本说右行 6 字，图上只有 4 个：切不出，整列退回
    out, flags = J.restep(_cells(), _col(), (0.0, 100.0), 100.0, [(3, 6, 5)], reading_order=reading_order)
    assert out is None and any("退回" in f for f in flags)


def test_default_impl_is_noop():
    from open_guji_cv.books.siku_zongmu import jiazhu_step as D
    assert D.page_note_runs("x", "y", "b", 1) is None
    res = object()
    assert D.apply(res, None, (0, 1), 1.0, [(1, 1, 1)]) == (res, [])
