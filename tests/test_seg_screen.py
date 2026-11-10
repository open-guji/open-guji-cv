"""切分筛查判据（`eval/seg_screen.py`，A22 F4①②、F7）：数据自造。"""
from types import SimpleNamespace

import numpy as np

from open_guji_cv.eval import seg_screen as ss
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells


def _col(col, slots, y0=100, period=100.0, flags=(), kinds=None):
    cells = [CellRec(slot=s, pos=s, y0=y0 + (s - 1) * period, y1=y0 + s * period, x0=0, x1=100,
                     kind=(kinds or {}).get(s, "char"), order=i) for i, s in enumerate(slots)]
    return ColumnCells(col=col, ok=True, n_body_slots=len(slots), cells=cells, period=period,
                       content_x=(0.0, 100.0), border_top=20.0, border_bottom=100 + len(slots) * period + 80,
                       flags=list(flags))


def _img(h, w=100):
    return np.full((h, w), 255, np.uint8)


def test_edge_ink_clean_column_is_none():
    cc = _col(1, [1, 2, 3])
    g = _img(500)
    g[120:180, 30:70] = 0                     # 格内的字
    assert ss.edge_ink(g, cc) is None


def test_edge_ink_reports_char_above_first_cell():
    cc = _col(1, [1, 2, 3])
    g = _img(500)
    g[30:90, 30:70] = 0                       # 第一格之上 60 行墨 > 0.5 格高
    e = ss.edge_ink(g, cc)
    assert e and e["top"] == 60 and e["bottom"] == 0


def test_edge_ink_ignores_frame_line_and_dust():
    cc = _col(1, [1, 2, 3])
    g = _img(500)
    g[40:46, :] = 0                           # 版框横线（满宽）
    g[60:61, 50:51] = 0                       # 尘点
    assert ss.edge_ink(g, cc) is None


def _gate(widths, flags=None, admitted=None):
    cols = [SimpleNamespace(col=i + 1, band_width=w, admitted=(admitted or {}).get(i + 1, True),
                            flags=(flags or {}).get(i + 1, [])) for i, w in enumerate(widths)]
    return SimpleNamespace(median_width=float(np.median(widths)), columns=cols)


def test_colnet_page():
    assert ss.colnet_page(_gate([200, 205, 198, 202])) == []
    hits = ss.colnet_page(_gate([200, 120, 205, 300]))
    assert [h["col"] for h in hits] == [2, 4]
    jz = ss.colnet_page(_gate([200, 120, 205], flags={2: ["column_width/side_ink 豁免：…"]}))
    assert jz == []


def test_layout_col_shift():
    page = PageCells(page=5, period=100.0, ref_w=200.0,
                     columns=[_col(1, [1, 2]), _col(2, [1, 2, 3]), _col(3, [2, 3]), _col(4, [1])])
    ok = {1: {"slots": [1, 2]}, 2: {"slots": [1, 2, 3]}, 3: {"slots": [2, 3]}, 4: {"slots": [1]}}
    assert ss.layout_col_shift(page, ok) is None
    shifted = {2: {"slots": [1, 2]}, 3: {"slots": [1, 2, 3]}, 4: {"slots": [2, 3]}}   # 表把列号整体 +1
    sh = ss.layout_col_shift(page, shifted)
    assert sh and sh["shift"] == -1 and sh["match"] == 3 and sh["match0"] == 0


def test_layout_col_shift_ignores_blank_cells():
    page = PageCells(page=5, period=100.0, ref_w=200.0,
                     columns=[_col(1, [1, 2, 3], kinds={3: "blank"})])
    assert ss.layout_col_shift(page, {1: {"slots": [1, 2]}}) is None


def test_pitch_free_ignored():
    cc = _col(1, [1], flags=["layout_unmerge（layout）：坏格…"])
    assert ss.pitch_free_ignored(cc, {"pitch": "free"})
    assert not ss.pitch_free_ignored(cc, {"slots": [1]})
    assert not ss.pitch_free_ignored(_col(1, [1]), {"pitch": "free"})
