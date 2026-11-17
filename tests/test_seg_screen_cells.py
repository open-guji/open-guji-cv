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


def test_align_drift_patterns():
    """史記 R017（11-14）：对位串错·疑整列错位。37:170:4 釣劈成加匈、曰賞并成豆，格态 bnObOO…Obb。
    当天按 SJ 抽看收紧：散在的单格 b（形近字认错）、考證列不报。"""
    assert ss.align_drift("bnObOOROOOROOROOOObb") == ["split"]
    assert ss.align_drift("OObbbbbbbOOOO") == ["pair", "run"]
    assert ss.align_drift("OOOBbBBBOOOOO") == ["run"]          # 20:108:3 剔劈成木成，后面放行器硬放了几格
    assert ss.align_drift("OOOBBBOOO") == []                  # 全放行的对不上（字形匹配弱）不报
    assert ss.align_drift("OOoooooOO") == []                  # 对得上只是没放行，不算
    assert ss.align_drift("ORRROOBOO") == []                  # 生僻字通道放行的不算
    assert ss.align_drift("OBbBOOO") == []                    # 一格没放行夹在放行的对不上之间：多是形近字
    assert ss.align_drift("ObOOObOROObOOO") == []             # 散在的单格没放行（11-14 前 ≥3 格就报）
    assert ss.align_drift("OOnnONOOO", "黄石公○按敢") == []    # 考證列：参校本没这段
    assert ss.align_drift("NnNnnNNNN") == ["pair"]             # 整列没配到参校字（42:84:8 真错）照报


def test_cell_states_uses_glyph_not_admit_char():
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit

    col = ColumnAdmit(col=1, chars=[AdmitRec(id="b:1:1:1", slot=1, admit=True, channel="match_ref", char="釣"),
                                    AdmitRec(id="b:1:1:2", slot=2, admit=False, char="匈"),
                                    AdmitRec(id="b:1:1:3", slot=3, admit=True, channel="rare_ref", char="虛")])
    ref = {"b:1:1:1": "釣", "b:1:1:3": "虛"}
    glyph = {"b:1:1:1": ["加"], "b:1:1:2": ["匈"], "b:1:1:3": ["虚"]}
    assert ss.cell_states(col, ref, glyph) == "BnR"


def test_screen_run_rows_keys_are_registered():
    """seg_screen_run 往 rows[...]／c[...] 里写的每个检查名都要在 CHECKS 里（11-14：align_drift 漏登记，有报出的册 seg check 直接 KeyError）。"""
    import re
    from pathlib import Path

    from open_guji_cv.eval import seg_screen_run as sr
    src = Path(sr.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r'rows\["(\w+)"\]\.append', src))
    assert used and used <= set(sr.CHECKS), used - set(sr.CHECKS)


# 史記 r61 切分闸误报与对照（A22 11-14，台账 R019）：格贴墨切的列（roster）里「一」等扁字整字成格，不算拆格；
# 真错（「二」上横并进上格、残点／字下半占一格）照报。数据是 r61 候选包 row_segment 的有字格 (格号, y0, y1)。
_TIGHT_COLS = {
    "35:15:8": [(2, 143, 254), (3, 274, 363), (4, 373, 478), (5, 540, 557), (6, 619, 702)],
    "35:18:2": [(2, 124, 243), (3, 259, 351), (4, 359, 465), (5, 515, 539), (6, 596, 692), (7, 749, 774)],
    "35:44:2": [(2, 137, 255), (3, 272, 365), (4, 380, 492), (5, 539, 560), (6, 619, 711), (7, 755, 820)],
    "35:88:2": [(2, 153, 277), (3, 285, 398), (4, 401, 526), (5, 568, 586), (6, 654, 754), (7, 790, 867)],
    "40:101:8": [(2, 151, 254), (3, 269, 358), (4, 373, 478), (5, 522, 537), (6, 601, 685), (7, 741, 796),
                 (8, 829, 922), (9, 955, 1027)],
    "vol01:87:6": [(1, 119, 218), (2, 715, 810), (3, 1327, 1345), (4, 1871, 1965), (5, 1993, 2084),
                   (6, 2103, 2201), (7, 2343, 2419)],                      # 殿本职名「皇十一子」
    "01:93:4": [(1, 33, 164), (2, 175, 271), (3, 274, 431), (4, 452, 473), (5, 508, 609), (6, 615, 698)],
    "01:94:2": [(1, 17, 150), (2, 164, 269), (3, 272, 426), (4, 451, 469), (5, 499, 594), (6, 614, 699)],
    "01:133:8": [(1, 13, 158), (2, 171, 295), (3, 295, 407), (4, 439, 460), (5, 501, 604), (6, 627, 645),
                 (7, 675, 829), (8, 863, 942)],
    "35:2:3": [(3, 290, 399), (4, 723, 825), (5, 1136, 1251), (6, 1577, 1679), (7, 1707, 1805), (8, 1822, 1929),
               (9, 2005, 2055), (10, 2176, 2272)],
    "01:90:2": [(3, 280, 362), (4, 362, 440), (5, 440, 545), (6, 545, 645), (7, 645, 753), (8, 753, 882),
                (9, 882, 1149)],                                          # 题署列「年表」两字一格（真错）
}


def test_odd_cell_heights_flat_glyph_in_tight_column():
    from types import SimpleNamespace as N

    def odd(key):
        cc = N(cells=[N(kind="char", slot=s, sub=None, y0=float(a), y1=float(b)) for s, a, b in _TIGHT_COLS[key]])
        return {(o["slot"], o["kind"]) for o in ss.odd_cell_heights(cc)}

    for key in ("35:15:8", "35:18:2", "35:44:2", "35:88:2", "40:101:8", "vol01:87:6"):
        assert not any(k == "short" for _s, k in odd(key)), key            # 扁字整字：不报
    assert (4, "short") in odd("01:93:4") and (4, "short") in odd("01:94:2")   # 上格吞了「二」的上横
    assert (6, "short") in odd("01:133:8") and (4, "short") not in odd("01:133:8")  # 残点贴着上字；同列「一」不报
    assert (9, "short") in odd("35:2:3")                                    # 字的下半
    assert (9, "tall") in odd("01:90:2")
