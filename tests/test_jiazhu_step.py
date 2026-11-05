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
    # 左行比右行多：分法与 ⌈N/2⌉ 不同；但右行塞不进 5 字、左行 5 字格高匀，图上只有这一种分法 → 不送审（v1.2）
    assert any(f.startswith("jiazhu_uneven_img:3-7") for f in flags)
    assert not any(f.startswith("jiazhu_uneven:") for f in flags)
    assert [c.order for c in reading_order(out)] == sorted(c.order for c in out)


def test_restep_uneven_unproven_still_sent_to_review():
    """左行 5 字疏密不匀（格高偏离大）：图上证明不了分法，照旧打 jiazhu_uneven 送审。"""
    img = _col()
    img[205:560, 8:42] = 255
    for y, h in ((205, 40), (260, 40), (315, 40), (370, 40), (440, 115)):
        img[y:y + h, 8:42] = 0
    out, flags = J.restep(_cells(), img, (0.0, 100.0), 100.0, [(3, 4, 5)], reading_order=reading_order)
    assert out is not None, flags
    assert any(f.startswith("jiazhu_uneven:3-7") for f in flags), flags


def test_seg_end_gap_finds_hollow_main_char():
    """段下正文字中间是空的（只有两边竖笔、缝中带断开）：缝中带判据找不到，白行判据找到它的顶。"""
    ink = np.zeros((600, 100), bool)
    ink[20:300, 10:40] = True                 # 夹注两行
    ink[20:300, 60:90] = True
    ink[330:355, 45:55] = True                # 正文字：缝中只有 25 行墨（不够 MAIN_RUN），之下只有两边竖笔
    ink[330:420, 15:22] = True
    ink[330:420, 78:85] = True
    ink[480:560, 15:85] = True                # 再下一字：实心
    assert J._seg_end(ink, 0, 600, 50, 100.0) == 480
    assert J._seg_end_gap(ink, 200, 480, 50, 100.0) == 330


def test_restep_falls_back_when_counts_disagree():
    # 整理本说右行 6 字，图上只有 4 个：切不出，整列退回
    out, flags = J.restep(_cells(), _col(), (0.0, 100.0), 100.0, [(3, 6, 5)], reading_order=reading_order)
    assert out is None and any("退回" in f for f in flags)


def test_default_impl_is_noop():
    from open_guji_cv.books.siku_zongmu import jiazhu_step as D
    assert D.page_note_runs("x", "y", "b", 1) is None
    res = object()
    assert D.apply(res, None, (0, 1), 1.0, [(1, 1, 1)]) == (res, [])


def test_seed_admit_sends_uneven_segment_to_review(monkeypatch):
    """列旗 jiazhu_uneven:<首>-<末> → 段内夹注格降审、带 doubt 码与 seg_kind；段外、正文、人裁格不动。"""
    from types import SimpleNamespace as NS

    from open_guji_cv.steps import seed_admit as sa
    cells = NS(columns=[NS(col=4, flags=["jiazhu_uneven:3-7：右 4 左 5（整理本分法），送审"])], alt_columns=[])
    monkeypatch.setattr(sa, "_opt", lambda ctx, kind, page: cells)

    def rec(slot, sub, channel="lib"):
        return NS(id=f"08:5:4:{slot}{sub}", slot=slot, sub=sub, char="甲", admit=True, channel=channel,
                  provenance="", doubts=[], evidence={})
    recs = [rec(3, "a"), rec(7, "b"), rec(5, "a", channel="human"), rec(8, ""), rec(2, ""), rec(6, "a")]
    # 6a：放行字＝库首选＝整理本字，图上有证据，不降
    mmap = {"08:5:4:6a": NS(candidates=[("甲", 0.9)]), "08:5:4:3a": NS(candidates=[("乙", 0.9)])}
    amap = {"08:5:4:6a": ("甲", "equal"), "08:5:4:3a": ("甲", "equal")}
    n = sa._jiazhu_uneven_pass(None, 5, [NS(col=4, chars=recs)], mmap, amap, {})
    assert n == 2
    for r in recs[:2]:
        assert not r.admit and r.doubts == ["jiazhu_uneven"] and r.evidence["seg_kind"] == "jiazhu_uneven"
        assert r.evidence["demoted_from"] == {"channel": "lib", "by": "jiazhu_uneven"}
    assert all(r.admit for r in recs[2:]) and recs[5].doubts == []
    # 没有这面列旗：什么都不做
    cells.columns[0].flags = ["alt_cut：x"]
    assert sa._jiazhu_uneven_pass(None, 5, [NS(col=4, chars=[rec(3, "a")])]) == 0


def test_restep_takes_back_raised_blank_row():
    """段从正文第 1 格起，格网在上面多抬了一格（−1 格、记空），那里是两行小字：收回段里当第一行（02:58:8）。"""
    img = np.full((800, 100), 255, np.uint8)
    for i in range(5):                        # 两行各 5 字，行距 100，从 y=10 起
        y = 10 + 100 * i
        img[y:y + 70, 58:92] = 0
        img[y:y + 70, 8:42] = 0
    img[520:600, 15:85] = 0                   # 段下正文
    cs = [Cell(slot=-1, y0=0, y1=100, x0=0, x1=100, kind="blank")]
    for k, s in enumerate(range(1, 6)):       # 格网把段压到 100 以下、少了一行
        y0 = 100 + 80 * k
        cs += [Cell(slot=s, y0=y0, y1=y0 + 80, x0=50, x1=100, kind="jiazhu_a", gap_center=50.0),
               Cell(slot=s, y0=y0, y1=y0 + 80, x0=0, x1=50, kind="jiazhu_b", gap_center=50.0)]
    cs += [Cell(slot=6, y0=500, y1=620, x0=0, x1=100, kind="char"),
           Cell(slot=7, y0=620, y1=800, x0=0, x1=100, kind="blank")]
    out, flags = J.restep(cs, img, (0.0, 100.0), 100.0, [(1, 5, 5)], reading_order=reading_order)
    assert out is not None, flags
    assert any(f.startswith("jiazhu_head：段 1 收回") for f in flags), flags
    assert not any(c.slot == -1 for c in out)
    a = sorted((c for c in out if c.kind == "jiazhu_a"), key=lambda c: c.slot)
    assert [c.slot for c in a] == [1, 2, 3, 4, 5] and a[0].y0 <= 10 and a[0].y1 >= 80


def test_raised_is_note_rejects_main_char():
    ink = np.zeros((200, 100), bool)
    ink[10:80, 10:40] = True
    ink[10:80, 60:90] = True
    assert J._raised_is_note(ink, 0, 100, 50, 100.0)
    ink[10:80, 15:85] = True                  # 横贯缝中的大字
    assert not J._raised_is_note(ink, 0, 100, 50, 100.0)
