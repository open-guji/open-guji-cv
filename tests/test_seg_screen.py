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


# ── ①c 漏切块 ────────────────────────────────────────────────────────────

def _orph_col():
    """列宽 100，四个字格（y 100–200、200–300、400–500、500–600），300–400 那个字没切进任何格。"""
    g = _img(800)
    boxes = [(20, y, 80, y + 100) for y in (100, 200, 400, 500)]
    for y in (100, 200, 300, 400, 500):
        g[y + 20:y + 80, 30:70] = 0
    return g, boxes


def test_orphan_reports_char_outside_boxes():
    g, boxes = _orph_col()
    hits = ss.orphan_ink(g, boxes)
    assert len(hits) == 1
    h = hits[0]
    assert h["where"] == "mid" and h["bbox"][1] == 320 and h["ratio"] == 1.0


def test_orphan_clean_column_and_no_boxes():
    g, boxes = _orph_col()
    g[300:400] = 255                                   # 中间那字擦掉
    assert ss.orphan_ink(g, boxes) == []
    assert ss.orphan_ink(g, []) == []


def test_orphan_strips_ruling_and_frame_lines():
    """界行（贯穿整列的竖线）把各字连成一块、版框横线落在格外：剥掉后都不报。"""
    g, boxes = _orph_col()
    g[300:400] = 255
    g[:, 48:51] = 0                                    # 界行穿过所有字
    g[30:36, :] = 0                                    # 上版框
    g[700:706, :] = 0                                  # 下版框
    assert ss.orphan_ink(g, boxes) == []


def test_orphan_ignores_small_specks_and_side_edges():
    g, boxes = _orph_col()
    g[300:400] = 255
    g[340:346, 40:46] = 0                              # 小墨点（< 150px）
    g[320:380, 0:15] = 0                               # 贴左边的邻列字边
    assert ss.orphan_ink(g, boxes) == []


def _tail_page():
    """两格（格高 100，界线 y=200）：上格字的竖笔拖到 235，下格字从 240 起——y=200 的格线劈了竖笔尾。"""
    cc = _col(1, [1, 2])
    g = _img(400)
    g[120:190, 30:70] = 0
    g[120:236, 40:50] = 0                     # 竖笔尾伸进下格 36 行（切割量 360px ≥ 0.025×格高²）
    g[240:290, 30:70] = 0
    return g, cc


class _Judge:
    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def assess(self, col_gray, x_lo, x_hi, y0, y1, y_line, seams, ink_threshold=128):
        self.calls.append((y0, y1, y_line, seams))
        return list(self.scores), [0, 0]


def test_cut_through_reports_stroke_tail_cut():
    g, cc = _tail_page()
    hits = ss.cut_through(g, cc)
    assert len(hits) == 1
    h = hits[0]
    assert (h["slot_above"], h["slot_below"]) == (1, 2) and h["cost"] == 360 and h["best"] == 0
    assert 36 <= h["move"] <= 39 and h["level"] == "中"


def test_cut_through_short_move_is_weak():
    """挪不到 CUT_WEAK_MOVE 格高的中档记「弱」（原线已贴着字缝，多是上下字笔画相触；seg check 只当提示，11-14）。"""
    cc = _col(1, [1, 2])
    g = _img(400)
    g[120:190, 30:70] = 0
    g[120:226, 40:55] = 0                     # 竖笔尾伸进下格 26 行、宽 15（切割量 390px）
    g[240:290, 30:70] = 0
    (h,) = ss.cut_through(g, cc)
    assert h["cost"] == 390 and h["move"] == 26 and h["level"] == "弱"


def test_cut_through_judge_gates_report():
    g, cc = _tail_page()
    ok = _Judge([0.90, 0.99])                 # 挪后归属更对：报
    assert len(ss.cut_through(g, cc, judge=ok)) == 1
    _y0, _y1, y_line, seams = ok.calls[0]
    assert y_line == 200 and seams[0] is None and int(seams[1][0]) >= 236
    assert ss.cut_through(g, cc, judge=_Judge([0.99, 0.85])) == []      # 挪后掉太多（挪进字内白缝）：不报
    assert len(ss.cut_through(g, cc, judge=_Judge([0.99, 0.93]))) == 1  # 掉不到 CUT_JUDGE（只动钩尖）：报


def test_cut_through_follows_seam_and_skips_blank_pairs():
    g, cc = _tail_page()
    seam = [200] * 100
    seam[38:52] = [238] * 14                  # Step3 折线绕到竖笔尾下面：没劈
    cc.cells[1].seam_top = seam
    assert ss.cut_through(g, cc) == []
    g2 = _img(400)
    cc2 = _col(1, [1, 2], kinds={1: "blank", 2: "blank"})
    g2[150:250, 40:50] = 0                    # 两格都空（墨不算字）：不看
    assert ss.cut_through(g2, cc2) == []


def _inner_gap_page():
    """三格（100–200–300–400）。字 1 主体 120–195、底横 201–210，字内白缝 195–201 正好压着 1|2 格线（望的王底横被切到下一格）；
    字 1 与字 2 之间的字缝 210–240 宽 30 行。"""
    cc = _col(1, [1, 2, 3])
    g = _img(500)
    g[120:195, 30:70] = 0
    g[201:210, 25:75] = 0
    g[240:290, 30:70] = 0
    g[320:380, 30:70] = 0
    return g, cc


def test_inner_gap_reports_seam_in_glyph_gap():
    """史記 R002（11-14）：格线落在字内白缝、挨着对不上参校字的格，旁边有宽得多的字缝 → 报。"""
    g, cc = _inner_gap_page()
    (h,) = ss.inner_gap(g, cc, {1: "b", 2: "b", 3: "O"})
    assert (h["slot_above"], h["slot_below"]) == (1, 2) and h["gap"] == 6 and h["alt_gap"] == 30 and h["move"] == 25
    assert h["piece"] == 0.18                 # 底横 9×50 ÷（底横＋字 2 的 50×40）
    assert ss.inner_gap(g, cc, {1: "O", 2: "O", 3: "O"}) == []          # 字都对得上：不看
    assert ss.inner_gap(g, cc, {1: "B", 2: "B", 3: "O"}) == []          # 对不上但已放行：不看（形近字认错居多）


def test_inner_gap_quiet_when_line_in_glyph_gap_is_widest():
    g = _img(500)
    cc = _col(1, [1, 2, 3])
    g[120:180, 30:70] = 0                     # 线落在字间缝 180–230 里（宽 50），附近没有更宽的缝
    g[230:290, 30:70] = 0
    g[320:380, 30:70] = 0
    assert ss.inner_gap(g, cc, {1: "b", 2: "b", 3: "b"}) == []


def test_inner_gap_quiet_when_line_already_in_wide_gap_or_far_side_empty():
    """殿本 99 册误报两类（11-14）：线已在 10px 以上的字缝里、旁边是「二」的笔间空白；宽缝外没字（列首留白）。"""
    g = _img(500)
    cc = _col(1, [1, 2, 3])
    g[120:190, 30:70] = 0                     # 字 1 到 190，字缝 190–210（20 行）压着 1|2
    g[210:215, 25:75] = 0                     # 「二」上横
    g[245:250, 25:75] = 0                     # 「二」下横，笔间空白 215–245（30 行）
    g[320:380, 30:70] = 0
    assert ss.inner_gap(g, cc, {1: "O", 2: "b", 3: "O"}) == []
    g = _img(500)
    cc = _col(1, [1, 2, 3])
    g[141:143, :] = 0                         # 列首框线残段
    g[185:197, 25:75] = 0                     # 字 1 只是一截扁笔，197–203 窄缝压着 1|2
    g[203:290, 30:70] = 0
    g[320:380, 30:70] = 0
    assert ss.inner_gap(g, cc, {1: "b", 2: "b", 3: "O"}) == []         # 143–185 的「宽缝」外只剩框线：是列首留白
    g[100:141, 30:70] = 0                     # 宽缝外有字：照报
    assert len(ss.inner_gap(g, cc, {1: "b", 2: "b", 3: "O"})) == 1


def test_inner_gap_skips_jiazhu_and_blank():
    g, cc = _inner_gap_page()
    cc.cells[1].sub = "a"                     # 2 号是夹注半格：不看
    assert ss.inner_gap(g, cc, {1: "b", 2: "b", 3: "O"}) == []
    g, cc = _inner_gap_page()
    cc.cells[0].kind = "blank"                # 1 号空格：不看
    assert ss.inner_gap(g, cc, {1: "b", 2: "b", 3: "O"}) == []


def test_slot_states_groups_halves_and_skips_circle():
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
    col = ColumnAdmit(col=1, chars=[AdmitRec(id="b:1:1:1", slot=1, admit=False, char="曽"),
                                    AdmitRec(id="b:1:1:2a", slot=2, admit=True, char="云"),
                                    AdmitRec(id="b:1:1:2b", slot=2, admit=False, char="三"),
                                    AdmitRec(id="b:1:1:3", slot=3, admit=False, char="四")])
    assert ss.slot_states(col, "bOnn") == {1: "b", 2: "On", 3: "n"}
    assert ss.slot_states(col, "bOnn", {"b:1:1:3": "○"}) == {1: "b", 2: "On", 3: "O"}


def test_inner_gap_R002_sj_frozen_columns():
    """史記 r64 main 冻结的 18 列（逐行墨宽、格、格态，`fixtures/inner_gap/R002_sj_r64.json`）：SJ 字形库线追报 15 列里
    报得出的 9 列（`ruler`）＋同批 13 册新查出、看图属实的 9 列（`new`：主／言的点、三的上横、海的头落到上一格）。
    各列该报的格线不能少（A22 11-14）。"""
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / "fixtures" / "inner_gap" / "R002_sj_r64.json").read_text(encoding="utf-8"))
    assert len(data) == 18
    for d in data:
        g = np.full((d["height"], d["width"]), 255, np.uint8)
        y = 0
        for val, n in d["ink_rle"]:
            g[y:y + n, :val] = 0
            y += n
        cells = [CellRec(slot=s, pos=s, y0=y0, y1=y1, x0=0, x1=d["width"], kind=k, order=i, sub=sub,
                         seam_top=None if st is None else [int(st)], seam_bottom=None if sb is None else [int(sb)])
                 for i, (s, sub, y0, y1, k, st, sb) in enumerate(d["cells"])]
        cc = ColumnCells(col=1, ok=True, n_body_slots=len(cells), cells=cells, period=d["period"],
                         content_x=(0.0, float(d["width"])), border_top=0.0, border_bottom=float(d["height"]))
        hits = ss.inner_gap(g, cc, {int(k): v for k, v in d["states"].items()})
        got = [f"{h['slot_above']}|{h['slot_below']}" for h in hits]
        assert set(d["expect"]) <= set(got), (d["col"], got)
        for h in hits:                # 同段窄缝线（SJ 11-15 看图：钉子一起挪的线）
            want = CHAIN_EXPECT.get((d["col"], f"{h['slot_above']}|{h['slot_below']}"))
            if want is not None:
                assert [f"{c['slot_above']}|{c['slot_below']}" for c in h["chain"]] == want, d["col"]


CHAIN_EXPECT = {   # SJ rev 1006446 钉子挪过的线：42:84:1 闕三皇三条、29:117:3 遂到王（3|4 正落在 2|3 该挪去的缝里）、15:170:7 列首三条
    ("42:84:1", "19|20"): ["18|19", "20|21"],
    ("29:117:3", "2|3"): ["3|4", "4|5", "5|6", "6|7"],
    ("15:170:7", "3|4"): ["1|2", "2|3"],
    ("17:157:6", "1|2"): [],
}


def test_two_glyphs_tall_cell_with_two_chars():
    """格高 2 倍、框住上下两个字（中间 20px 白缝）：报；同一格只有一个高字（竖笔连着）不报。"""
    cc = _col(1, [1])
    cell = cc.cells[0].model_copy(update={"y1": 300.0})       # y 100–300
    g = _img(400)
    g[110:190, 30:70] = 0
    g[210:290, 30:70] = 0
    r = ss.two_glyphs(g, cell, cc.content_x, 100.0)
    assert r and r["ratio"] == 2.0 and len(r["parts"]) == 2 and r["gap"] == 20
    g2 = _img(400)
    g2[110:290, 45:55] = 0
    assert ss.two_glyphs(g2, cell, cc.content_x, 100.0) is None


def test_two_glyphs_quiet_on_normal_cell_and_flat_strokes():
    cc = _col(1, [1])
    g = _img(400)
    g[110:140, 30:70] = 0
    g[160:190, 30:70] = 0                     # 一格一字（呂）：格高 1 倍不看
    assert ss.two_glyphs(g, cc.cells[0], cc.content_x, 100.0) is None
    cell = cc.cells[0].model_copy(update={"y1": 250.0})
    g2 = _img(400)
    for y in (120, 160, 200, 240):            # 高格里几道扁横（二、三）：每段都矮
        g2[y:y + 8, 20:80] = 0
    assert ss.two_glyphs(g2, cell, cc.content_x, 100.0) is None
