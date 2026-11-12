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
