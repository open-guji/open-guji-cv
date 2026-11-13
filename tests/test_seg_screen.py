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


def test_edge_frame_only():
    cc = _col(1, [1, 2, 3])                   # 格 100–400，下版框线在 480
    cc.border_bottom = 400.0
    g = _img(500)
    g[392:398, 5:95] = 0                      # 末格里只有贴着下框的粗横线
    g[350:351, 50:52] = 0                     # 霉点不算
    assert ss.edge_frame_only(g, cc) == [3]
    g[330:340, 20:80] = 0                     # 格中间的「一」：离框线远 → 是字
    assert ss.edge_frame_only(g, cc) == []


def test_edge_frame_only_skips_blank_and_unknown_border():
    cc = _col(1, [1, 2, 3], kinds={3: "blank"})
    cc.border_bottom = 400.0
    g = _img(500)
    g[392:398, 5:95] = 0
    assert ss.edge_frame_only(g, cc) == []
    cc2 = _col(1, [1, 2, 3])
    cc2.border_bottom = None
    assert ss.edge_frame_only(g, cc2) == []


def test_layout_fallback_cols():
    page = PageCells(page=5, period=100.0, ref_w=200.0, columns=[
        _col(1, [1], flags=["layout_off：坏格…"]), _col(2, [1]), _col(3, [1], flags=["layout_unmerge（layout）：…"])])
    assert ss.layout_fallback_cols(page) == [1, 3]
    page.columns[2].flags = []
    assert ss.layout_fallback_cols(page) == []


def _borders(right, left, width=1000, n=6, pitch=100.0):
    from open_guji_cv.seg.frame_types import BorderDetectionResult, HLine, VLine
    xs = [right + i * pitch for i in range(n)]
    xs[-1] = width - left
    return BorderDetectionResult(width=width, height=800, top=HLine(y_at_right=50.0, slope=0.0, kind="top"),
                                 bottom=HLine(y_at_right=750.0, slope=0.0, kind="bottom"),
                                 verticals=[VLine(x_at_top=x, slope=0.0) for x in xs])


def test_margin_outliers():
    m = {p: ss.frame_margins(_borders(200, 300)) for p in range(2, 22, 2)}
    assert m[2]["right"] == 200 and m[2]["left"] == 300
    assert ss.margin_outliers(m) == []
    m[8] = ss.frame_margins(_borders(320, 300))      # 右框没印出、整网左挪一列多
    hits = ss.margin_outliers(m)
    assert [(h["page"], h["side"]) for h in hits] == [(8, "right")]


def test_seg_primitive_frame_only_edge_cells():
    from open_guji_cv.seg.profile import frame_only_edge_cells
    g = _img(500)
    g[392:398, 5:95] = 0                      # 末格只有贴下框的线
    g[130:170, 30:70] = 0                     # 首格有字
    spans = [(100, 200), (200, 300), (300, 400)]
    assert frame_only_edge_cells(g, spans, (0, 100), 100.0, 400.0, 100.0) == [2]
    assert frame_only_edge_cells(g, spans, (0, 100), 100.0, None, 100.0) == []
