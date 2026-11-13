"""eval/seg_screen 的格级判据（SJ 史記快筛搬进来，2026-11-12）：墨账、列端版框、字块边线、夹注并格、对格号。"""
import numpy as np

from open_guji_cv.eval import seg_screen as ss


def _col():
    g = np.full((400, 100), 255, np.uint8)
    g[20:80, 30:70] = 0          # 字 1
    g[120:180, 30:70] = 0        # 字 2
    return g


def test_ink_ledger_foreign_when_box_eats_neighbour():
    g = _col()
    cells = [("b:1:1:1", (20, 10, 80, 135), 1, None), ("b:1:1:2", (20, 135, 80, 200), 2, None)]
    led = ss.ink_ledger(g, cells)
    assert led["b:1:1:1"]["foreign"] > 0 and "FOR" in ss.ledger_flags(led["b:1:1:1"])
    ok = ss.ink_ledger(g, [("b:1:1:1", (20, 10, 80, 100), 1, None), ("b:1:1:2", (20, 100, 80, 200), 2, None)])
    assert ok["b:1:1:1"]["foreign"] == 0 and ss.ledger_flags(ok["b:1:1:1"]) == []


def test_ink_ledger_jiazhu_other_half_not_foreign():
    g = np.full((200, 100), 255, np.uint8)
    g[20:80, 55:90] = 0
    g[20:80, 10:45] = 0
    cells = [("b:1:1:1a", (50, 10, 95, 90), 1, "a"), ("b:1:1:1b", (5, 10, 60, 90), 1, "b")]
    assert ss.ink_ledger(g, cells)["b:1:1:1b"]["foreign"] == 0


def test_ink_ledger_rule_line():
    g = _col()
    g[:, 50] = 0                 # 贯穿界行
    led = ss.ink_ledger(g, [("b:1:1:1", (20, 10, 80, 100), 1, None)])
    assert "Lv" in ss.ledger_flags(led["b:1:1:1"])


def test_end_frame_hits():
    g = np.full((300, 100), 255, np.uint8)
    g[12:14, 5:95] = 0           # 上版框线进了首格
    g[30:80, 30:70] = 0
    hits = ss.end_frame_hits(g, [(0, 10, 100, 90), (0, 100, 100, 200)], border_top=12, border_bottom=290)
    assert list(hits) == [0] and hits[0][0][0] == "top"


def test_patch_edge_lines():
    p = np.full((60, 50), 255, np.uint8)
    p[1:3, 2:48] = 0             # 上边一条薄横线
    p[15:50, 10:40] = 0          # 字身
    assert "top" in ss.patch_edge_lines(p) and "bot" not in ss.patch_edge_lines(p)


def test_jiazhu_wide():
    assert ss.jiazhu_wide((0, 0, 80, 10), 100, "a") and not ss.jiazhu_wide((0, 0, 40, 10), 100, "a")
    assert not ss.jiazhu_wide((0, 0, 80, 10), 100, None)


def test_pin_and_layout_slots():
    pin = [{"slot": -1, "sub": None, "kind": "char"}, {"slot": 1, "sub": None, "kind": "char"}]
    assert ss.pin_slots_diff({"-1", "1"}, pin) == ""
    assert "产物有钉子无 2" in ss.pin_slots_diff({"-1", "1", "2"}, pin)
    row = {"slots": [1, 2, 3], "notes": [3], "half": [2]}
    assert ss.layout_slots_diff({"1", "2a", "3a", "3b"}, row) is None
    assert ss.layout_slots_diff({"1", "2b", "3a", "3b"}, row) is None          # 半格只切出 b 也算对上
    assert ss.layout_slots_diff({"2", "3a", "3b", "4"}, row) == "同数"
    assert ss.layout_slots_diff({"1", "2a"}, row).startswith("异数")


def test_odd_cell_heights():
    from types import SimpleNamespace as N
    cells = [N(kind="char", slot=i, sub=None, y0=i * 100.0, y1=i * 100.0 + h)
             for i, h in enumerate([90, 95, 100, 180, 92, 40], 1)]
    odd = ss.odd_cell_heights(N(cells=cells))
    assert [(o["slot"], o["kind"]) for o in odd] == [(4, "tall"), (6, "short")]
    assert ss.odd_cell_heights(N(cells=cells[:3])) == []


def test_page_pitch_and_half_width():
    from types import SimpleNamespace as N

    def cell(slot, y0, h, sub=None, x0=0, x1=100, kind="char"):
        return N(slot=slot, sub=sub, y0=y0, y1=y0 + h, x0=x0, x1=x1, kind=kind)
    good = N(col=1, ok=True, flags=[], cells=[cell(i, i * 100, 100) for i in range(1, 11)])
    squeezed = N(col=2, ok=True, flags=[], cells=[cell(i, i * 85, 85) for i in range(1, 11)])     # 整列格网缩了 15%
    merged = N(col=3, ok=True, flags=[], cells=[cell(1, 0, 100), cell(2, 100, 180), *[cell(i, i * 100, 100) for i in range(3, 9)]])
    page = N(columns=[good, squeezed, merged])
    p = ss.page_pitch(page)
    assert p == 100
    assert ss.pitch_outliers(good, p) is None
    assert ss.pitch_outliers(squeezed, p)["col_ratio"] == 0.85
    assert [o["slot"] for o in ss.pitch_outliers(merged, p)["cells"]] == [2]
    jz = N(cells=[cell(5, 0, 50, "a", 0, 50), cell(5, 0, 50, "b", 50, 100),
                  cell(6, 50, 50, "a", 0, 80), cell(6, 50, 50, "b", 80, 100)])               # 6 号中缝切偏
    hits = ss.half_width_outliers(jz, 50)
    assert {(o["slot"], o["sub"]) for o in hits} == {(6, "a"), (6, "b"), (6, "ab")}


def test_ref_confirmed_exempts_only_verified_cells():
    """史記 R011／R013（2026-11-13）：格高／半格宽离群、但参校字在字形匹配前 3 名、邻格无反证的格不报。"""
    from open_guji_cv.products.kinds.recog import ColumnMatch, MatchRec, PageMatch

    def m(slot, sub, cands):
        return MatchRec(id=f"01:5:1:{slot}{sub or ''}", slot=slot, sub=sub, verdict="unsure",
                        candidates=[(ch, 0.9) for ch in cands])
    glyph = PageMatch(page=5, columns=[ColumnMatch(col=1, chars=[
        m(1, None, ["天", "夫"]), m(2, None, ["二", "一"]), m(3, None, ["人"]),
        m(4, None, ["日", "曰"]), m(5, None, ["軍", "車"]), m(6, "a", ["集"]), m(6, "b", ["解"])])])

    class R:                                          # align_ref 产物只要 coord[].id／ref_char
        def __init__(self, i, c):
            self.id, self.ref_char = i, c

    class A:
        coord = (R("01:5:1:1", "天"), R("01:5:1:2", "一"), R("01:5:1:3", "人"), R("01:5:1:4", "參"),
                 R("01:5:1:5", "軍"), R("01:5:1:6a", "集"), R("01:5:1:6b", "解"))
    conf = ss.ref_confirmed(glyph, A())
    assert conf[(1, 2, "")] is True and conf[(1, 4, "")] is False
    assert ss.ref_ok_cell(conf, 1, 2, None)           # 扁字「一」：本格、上下邻格都证实
    assert not ss.ref_ok_cell(conf, 1, 4, None)       # 本格对不上参校字（拆格把「參」切成「日」）
    assert not ss.ref_ok_cell(conf, 1, 3, None)       # 本格对、下邻格反证
    assert ss.ref_ok_cell(conf, 1, 6, "ab")           # 夹注 a/b 两半都证实
    assert not ss.ref_ok_col(conf, 1)                 # 不到 PITCH_COL_MIN 格不判整列


def test_block_tall():
    # 殿本 vol06 147:3:3：格高 128，Step4 字块连上长竖线高 427
    assert ss.block_tall(427, 128) == 3.34
    assert ss.block_tall(150, 128) is None          # 带 padding 的人工定框格，1.2 倍
    assert ss.block_tall(60, 40) is None            # 小格取整误差：倍数够但多出不到 24px
    assert ss.block_tall(100, 0) is None
