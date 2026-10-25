# -*- coding: utf-8 -*-
"""`scripts/dzg_layout.py`（daizhige 逐列本 → 逐列格位表）与 `row_segment.layout_prior` 读表。数据全在 tmp 里现造。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_ROOT))
_SPEC = importlib.util.spec_from_file_location("dzg_layout", _ROOT / "dzg_layout.py")
dl = importlib.util.module_from_spec(_SPEC)
sys.modules["dzg_layout"] = dl
_SPEC.loader.exec_module(dl)


def test_column_layout_slots_notes_and_halves():
    """格位 pos → slot = pos+1；夹注右行 a、左行 b，两半都有的进 notes，只一半的进 half。

    样例是殿本 vol05 p37 c6 的实形：小注右行「無卷數」「浙江」中间空一格，那一格只有左半。"""
    col = {"no": 5, "runs": [
        {"t": "text", "start": 0, "s": "易林疑說"},
        {"t": "note", "start": 4, "r": [[0, "無卷數"], [4, "浙江"]], "l": [[0, "汪啟淑家藏本"]]}]}
    lay = dl.column_layout(col)
    assert lay["slots"] == list(range(1, 11))
    assert lay["notes"] == [5, 6, 7, 9, 10]
    assert lay["half"] == [8]                      # 右行空格：只有左半「家」
    assert lay["raised"] == 0


def test_column_layout_raised_and_empty():
    lay = dl.column_layout({"no": 0, "runs": [{"t": "text", "start": -1, "s": "上諭朕"}]})
    assert lay["slots"] == [-1, 1, 2] and lay["raised"] == 1      # 出格抬头：-1 之后是 1，跳过 0
    assert dl.column_layout({"no": 0, "runs": []}) is None


def test_build_maps_half_leaf_columns(tmp_path):
    """我们一页 = daizhige 一个半叶：side=1 取 no 9–17，列号 no%9+1。"""
    dz = tmp_path / "corpus" / "daizhige"
    dz.mkdir(parents=True)
    rec = {"id": "0001-0010", "page": "1-3a", "cols": [
        {"no": 0, "runs": [{"t": "text", "start": 2, "s": "甲乙"}]},
        {"no": 9, "runs": [{"t": "text", "start": 0, "s": "丙"}]},
        {"no": 11, "runs": [{"t": "text", "start": 1, "s": "丁戊"}]}]}
    (dz / "0001.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    pm = [{"vol": "vol01", "page": 7, "kind": "text", "dzg_kind": "full", "dzg_id": "0001-0010", "side": 1},
          {"vol": "vol01", "page": 8, "kind": "blank", "dzg_kind": "empty", "dzg_id": "0001-0010", "side": 0}]
    (dz / "page_map.jsonl").write_text("".join(json.dumps(m) + "\n" for m in pm), encoding="utf-8")
    rows = dl.build(tmp_path)
    assert [(r["page"], r["col"], r["slots"]) for r in rows] == [(7, 1, [1]), (7, 3, [2, 3])]
    # 同一页被 page_map 映了两次（同一列出两行）：不知信哪行，整列剔除
    (dz / "page_map.jsonl").write_text("".join(json.dumps(m) + "\n" for m in pm + pm[:1]), encoding="utf-8")
    assert dl.build(tmp_path) == []


def test_row_segment_load_layout_and_fingerprint(tmp_path):
    from open_guji_cv.steps import row_segment as RS
    p = tmp_path / "layout.jsonl"
    p.write_text(json.dumps({"vol": "vol04", "page": 23, "col": 1, "slots": [3, 4], "notes": [],
                             "half": [], "raised": 0}) + "\n"
                 + json.dumps({"vol": "vol05", "page": 1, "col": 2, "slots": [1], "notes": [],
                               "half": [], "raised": 0}) + "\n", encoding="utf-8")
    assert set(RS.load_layout(str(p), "vol04")) == {(23, 1)}
    on = RS.RowSegmentParams(layout_prior=str(p))
    assert len(on.layout_fingerprint) == 16
    # 表不在：开着的开关不能悄悄当空表（同 colgold_prior）
    import pytest
    with pytest.raises(FileNotFoundError):
        RS.load_layout(str(tmp_path / "nope.jsonl"), "vol04")
    with pytest.raises(ValueError):
        RS.RowSegmentParams(layout_prior=str(tmp_path / "nope.jsonl"))
    off = RS.RowSegmentParams()
    assert off.layout_prior == "" and off.layout_fingerprint == ""     # 关着时参数逐字段不变


def test_layout_path_follows_corpus_dir(tmp_path, monkeypatch):
    """表路径口径同 colgold：corpus/… 走整理本目录（#198 起迁过中心库的工作区在数据目录）。"""
    from open_guji_cv.steps.row_segment import _layout_path
    (tmp_path / "corpus" / "daizhige").mkdir(parents=True)
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    assert _layout_path("corpus/daizhige/layout_slots.jsonl") == tmp_path / "corpus" / "daizhige" / "layout_slots.jsonl"
    assert _layout_path(str(tmp_path / "x.jsonl")) == tmp_path / "x.jsonl"


def test_layout_prior_defaults_on_when_the_workspace_has_the_table(tmp_path, monkeypatch):
    """2026-10-22 起缺省开：工作区有 corpus/daizhige/layout_slots.jsonl 就用，没有（无逐列本的书）就当关、不报错。"""
    from open_guji_cv.steps import row_segment as RS
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    assert RS.RowSegmentParams().layout_prior == ""
    t = tmp_path / "corpus" / "daizhige" / "layout_slots.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text(json.dumps({"vol": "vol04", "page": 23, "col": 1, "slots": [3], "notes": [],
                             "half": [], "raised": 0}) + "\n", encoding="utf-8")
    on = RS.RowSegmentParams()
    assert on.layout_prior == RS.DEFAULT_LAYOUT and len(on.layout_fingerprint) == 16
    assert RS.RowSegmentParams(layout_prior="").layout_prior == ""        # 书 yaml 写空串＝关


def test_row_segment_off_switches_not_in_params_dump(tmp_path):
    """缺省关的开关不进 dump：params_hash 与加这些字段之前（v0.4.5）逐位相同（冻结册升版不报「参数变了」，D 10-19）；开着照常进。"""
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps import row_segment as RS
    off = RS.RowSegmentParams().model_dump()
    for k in ("colgold_prior", "colgold_fingerprint", "yolo_merge", "yolo_model_dir", "yolo_fingerprint",
              "yolo_conf", "yolo_cover", "yolo_max_h", "layout_prior", "layout_fingerprint"):
        assert k not in off, k
    p = tmp_path / "layout.jsonl"
    p.write_text(json.dumps({"vol": "vol04", "page": 23, "col": 1, "slots": [3], "notes": [],
                             "half": [], "raised": 0}) + "\n", encoding="utf-8")
    on = RS.RowSegmentParams(layout_prior=str(p))
    d = on.model_dump()
    assert d["layout_prior"] == str(p) and len(d["layout_fingerprint"]) == 16
    assert params_hash(on) != params_hash(RS.RowSegmentParams())


def test_cut_rows_counts_only_lines_through_ink():
    """格线穿字判据：线落在字缝里不算，横穿字身才算；空格之间、夹注 a/b 之间不算。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _cut_rows
    img = np.full((300, 100), 255, np.uint8)
    img[10:90, 20:80] = 0                      # 字一：10–90
    img[110:190, 20:80] = 0                    # 字二：110–190
    ok = [C(y0=0, y1=100, kind="char", sub=None, slot=1), C(y0=100, y1=200, kind="char", sub=None, slot=2),
          C(y0=200, y1=300, kind="blank", sub=None, slot=3)]
    assert _cut_rows(img, ok) == 0
    bad = [C(y0=0, y1=50, kind="char", sub=None, slot=1), C(y0=50, y1=150, kind="char", sub=None, slot=2),
           C(y0=150, y1=300, kind="char", sub=None, slot=3)]
    assert _cut_rows(img, bad) == 2
    jz = [C(y0=0, y1=100, kind="jiazhu_a", sub="a", slot=1), C(y0=50, y1=100, kind="jiazhu_b", sub="b", slot=1)]
    assert _cut_rows(img, jz) == 0


def test_blank_frame_junk_only_touches_column_ends_with_frame_ink():
    """列端框线残渣：表说该空的首／末格里只有满宽横线就记空；像字的墨、列中段的格、碎墨多的格都不动。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((500, 100), 255, np.uint8)
    img[20:26, 0:100] = 0                      # 列首格：一条满宽版框线
    img[120:180, 30:70] = 0                    # 第 2 格：字
    img[220:280, 30:70] = 0                    # 第 3 格：字
    img[420:480, 30:70] = 0                    # 列尾格：表说该空，图上却是字 → 不动
    mk = lambda slot, y0: C(slot=slot, y0=y0, y1=y0 + 100, kind="char", sub=None)
    cells = [mk(1, 0), mk(2, 100), mk(3, 200), C(slot=4, y0=300, y1=400, kind="blank", sub=None), mk(5, 400)]
    n = _blank_frame_junk(img, cells, {2, 3}, (0, 100), 128, 100.0)
    assert n == 1 and cells[0].kind == "blank" and cells[4].kind == "char"
    # 列中段：表说该空的第 3 格里只有横线，但它不是列端 → 不动
    img2 = img.copy(); img2[220:280] = 255; img2[240:246, :] = 0
    cells2 = [mk(1, 0), mk(2, 100), mk(3, 200), mk(5, 400)]
    _blank_frame_junk(img2, cells2, {2, 5}, (0, 100), 128, 100.0)
    assert cells2[2].kind == "char"


def test_blank_frame_junk_covers_table_empty_run_at_column_end():
    """首字上方隔着一个空格的碎墨（表空格段里、不是物理首格）也记空；表的首字本身不动。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((400, 100), 255, np.uint8)
    img[140:150, 45:52] = 0                    # 第 2 格：一点碎墨
    img[220:280, 30:70] = 0                    # 第 3 格：表的首字
    mk = lambda slot, y0, kind="char": C(slot=slot, y0=y0, y1=y0 + 100, kind=kind, sub=None)
    cells = [mk(1, 0, "blank"), mk(2, 100), mk(3, 200), mk(4, 300, "blank")]
    assert _blank_frame_junk(img, cells, {3}, (0, 100), 128, 100.0) == 1
    assert cells[1].kind == "blank" and cells[2].kind == "char"


def test_split_chars_counts_lines_through_one_glyph_only():
    """劈字：格线把一个连通体劈成两段、两段都占它高的三成以上才算；擦过字头、落在字缝里都不算。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _split_chars
    img = np.full((300, 100), 255, np.uint8)
    img[10:90, 45:55] = 0                      # 字一：一竖，10–90
    img[120:130, 20:80] = 0                    # 字二：「二」上横
    img[170:180, 20:80] = 0                    #       「二」下横
    mk = lambda slot, y0, y1: C(slot=slot, y0=y0, y1=y1, kind="char", sub=None)
    assert _split_chars(img, [mk(1, 0, 100), mk(2, 100, 200)], 100.0) == 0
    assert _split_chars(img, [mk(1, 0, 50), mk(2, 50, 200)], 100.0) == 1        # 竖从中间劈开
    assert _split_chars(img, [mk(1, 0, 20), mk(2, 20, 200)], 100.0) == 0        # 只擦掉字头一成
    assert _split_chars(img, [mk(1, 0, 150), mk(2, 150, 200)], 100.0) == 0      # 落在「二」两横之间（这一型靠违表格数）


def test_merged_cuts_finds_two_glyphs_in_one_cell():
    """挤格：一格的墨高过 1.25 格、中间有白缝分成两段且两段都高过 0.4 格，给出缝中线；一个高字、字带框线都不算。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _merged_cuts
    img = np.full((400, 100), 255, np.uint8)
    img[10:80, 40:60] = 0                      # 字一 10–80
    img[90:150, 40:60] = 0                     # 字二 90–150，缝在 80–90
    img[200:330, 40:60] = 0                    # 一个高字 200–330，没有缝
    img[340:345, 10:90] = 0                    # 高字下面的细横（框线）
    mk = lambda slot, y0, y1, kind="char": C(slot=slot, y0=y0, y1=y1, kind=kind, sub=None)
    cuts = _merged_cuts(img, [mk(1, 0, 160), mk(2, 190, 350)], 100.0)
    assert len(cuts) == 1 and 80 <= cuts[0] <= 90
    assert _merged_cuts(img, [mk(1, 0, 160, "blank")], 100.0) == []


def test_uneven_counts_char_cells_far_from_period():
    from types import SimpleNamespace as C
    from open_guji_cv.steps.row_segment import _uneven
    mk = lambda y0, y1, kind="char": C(y0=y0, y1=y1, kind=kind)
    assert _uneven([mk(0, 100), mk(100, 175), mk(175, 320), mk(320, 360, "blank"), mk(360, 400, "jiazhu_a")], 100.0) == 1


def test_mask_misses_counts_both_directions():
    from types import SimpleNamespace as C
    from open_guji_cv.steps.row_segment import _mask_misses
    cells = [C(slot=1, kind="blank"), C(slot=2, kind="char"), C(slot=3, kind="char"), C(slot=4, kind="blank")]
    assert _mask_misses(cells, {2, 3}) == 0
    assert _mask_misses(cells, {3, 4}) == 2     # 第 2 格表说空却有字，第 4 格表说有字却空


def test_blank_frame_junk_blanks_ink_crossing_column_edges():
    """印章、墨污越过界行（墨伸到列的左右边上）：在表空格段里记空；守在列内的字不动；表认下的格不动。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((500, 100), 255, np.uint8)
    img[10:90, 0:100:7] = 0                    # 第 1 格：印章笔画，满宽散开、伸到两边
    img[110:190, 0:30] = 0                     # 第 2 格：印泥从左边伸进来
    img[220:280, 30:70] = 0                    # 第 3 格：表的首字
    img[310:390, 0:100:9] = 0                  # 第 4 格：越界墨，但表说有字 → 不动
    mk = lambda slot, y0: C(slot=slot, y0=y0, y1=y0 + 100, kind="char", sub=None)
    cells = [mk(1, 0), mk(2, 100), mk(3, 200), mk(4, 300), mk(5, 400)]
    img[420:480, 30:70] = 0                    # 第 5 格：表说空、却是守在列内的字 → 不动（表可能漏字）
    assert _blank_frame_junk(img, cells, {3, 4}, (0, 100), 128, 100.0) == 2
    assert [c.kind for c in cells] == ["blank", "blank", "char", "char", "char"]


def test_blank_frame_junk_blanks_speckle_that_forms_no_strokes():
    """印章压着的表空格：墨是成片的小墨点、连不成笔画，没伸到列边也记空；连成笔画的字不动。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((400, 100), 255, np.uint8)
    img[20:80, 30:70] = 0                      # 第 1 格：表的首字
    for y in range(115, 190, 8):               # 第 2 格：印泥斑点，3×3 的小点，守在列内
        for x in range(20, 80, 8):
            img[y:y + 3, x:x + 3] = 0
    img[320:380, 30:70] = 0                    # 第 4 格：表说空、却是连成笔画的字 → 不动
    mk = lambda slot, y0: C(slot=slot, y0=y0, y1=y0 + 100, kind="char", sub=None)
    cells = [mk(1, 0), mk(2, 100), C(slot=3, y0=200, y1=300, kind="blank", sub=None), mk(4, 300)]
    assert _blank_frame_junk(img, cells, {1}, (0, 100), 128, 100.0) == 1
    assert [c.kind for c in cells] == ["char", "blank", "blank", "char"]


def test_blank_frame_junk_blanks_cells_holding_only_thin_vertical_lines():
    """列端表空格里墨只是一两道竖线（印框的边）→ 记空；表空格里真有一个字 → 不动。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((300, 100), 255, np.uint8)
    img[0:100, 30:70] = 0                      # 第 1 格：表的首字
    img[100:200, 40:46] = 0                    # 第 2 格：一道竖线
    img[110:190, 88:94] = 0                    #          又一道
    img[220:280, 30:70] = 0                    # 第 3 格：一个字
    mk = lambda slot, y0, kind="char": C(slot=slot, y0=y0, y1=y0 + 100, kind=kind, sub=None)
    cells = [mk(1, 0), mk(2, 100, "jiazhu_solo"), mk(3, 200)]
    assert _blank_frame_junk(img, cells, {1}, (0, 100), 128, 100.0) == 1
    assert [c.kind for c in cells] == ["char", "blank", "char"]


def test_blank_frame_junk_whole_column_when_table_says_empty():
    """表说整列空（卷末空列）：整列都是表空格段，印章记空。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((300, 100), 255, np.uint8)
    img[110:190, 0:100:6] = 0                  # 中间那格：印章
    mk = lambda slot, y0: C(slot=slot, y0=y0, y1=y0 + 100, kind="char", sub=None)
    cells = [C(slot=1, y0=0, y1=100, kind="blank", sub=None), mk(2, 100), C(slot=3, y0=200, y1=300, kind="blank", sub=None)]
    assert _blank_frame_junk(img, cells, set(), (0, 100), 128, 100.0) == 1
    assert cells[1].kind == "blank"


def test_layout_row_fills_trailing_empty_columns():
    """表只记有字的列：这一页最后一列表行之后的列是整列空；表里没有这一页、或列号在中间缺的，不猜。"""
    from open_guji_cv.steps.row_segment import _layout_row
    layout = {(5, 1): {"slots": [1, 2]}, (5, 3): {"slots": [1]}}
    assert _layout_row(layout, 5, 1) == {"slots": [1, 2]}
    assert _layout_row(layout, 5, 2) is None
    assert _layout_row(layout, 5, 4)["slots"] == []
    assert _layout_row(layout, 6, 1) is None


def test_blank_frame_junk_blanks_table_empty_cells_in_the_seal_box():
    """印框记空：印框里、表说该空的列端格（字格、單行小注格）记空，哪怕墨连成笔画像字；
    印框里表说有字的格、印框外的格都不动。"""
    from types import SimpleNamespace as C
    import numpy as np
    from open_guji_cv.steps.row_segment import _blank_frame_junk
    img = np.full((500, 100), 255, np.uint8)
    for k in range(5):
        img[k * 100 + 20:k * 100 + 80, 30:70] = 0              # 每格一块成笔画的墨
    kinds = ["char", "char", "char", "jiazhu_solo", "char"]
    cells = [C(slot=k + 1, y0=k * 100, y1=k * 100 + 100, kind=kd, sub=None) for k, kd in enumerate(kinds)]
    in_seal = lambda c: c.slot in (1, 3, 4)
    assert _blank_frame_junk(img, cells, {3}, (0, 100), 128, 100.0, in_seal) == 2
    assert [c.kind for c in cells] == ["blank", "char", "char", "blank", "char"]


def test_in_seal_measures_cell_overlap_with_the_seal_box_in_page_coords():
    """大印（无笔画掩码）：格与印框（规范空间 x0, y0, x1, y1）重叠 ≥ 一半。"""
    from types import SimpleNamespace as C
    from open_guji_cv.steps.row_segment import _in_seal
    mapper = C(quad_tr=lambda x0, y0, x1, y1: [(x0 + 1000, y0), (x1 + 1000, y0), (x1 + 1000, y1), (x0 + 1000, y1)])
    f = _in_seal([(1000, 0, 1100, 150, None)], mapper)       # 印框盖住列图 y 0..150
    cell = lambda y0: C(x0=0, x1=100, y0=y0, y1=y0 + 100)
    assert f(cell(0)) and f(cell(50)) and not f(cell(110))     # 重叠 1、0.5、0.4
    assert _in_seal([], mapper) is None and _in_seal([(0, 0, 1, 1, None)], None) is None


def test_under_stain_is_the_column_head_under_a_big_seal_only():
    """列首格（版框顶下一个 period）一半以上在大印框里才算；小印（有笔画掩码）、列首格下面才进印框的都不算。"""
    import numpy as np
    from types import SimpleNamespace as C
    from open_guji_cv.steps.row_segment import _under_stain
    mapper = C(quad_tr=lambda x0, y0, x1, y1: [(x0 + 1000, y0), (x1 + 1000, y0), (x1 + 1000, y1), (x0 + 1000, y1)])
    big = (1000, 300, 1900, 1200, None)
    assert _under_stain([big], mapper, (0, 100), 300, 100)          # 列首 300..400 整格在印里
    assert not _under_stain([big], mapper, (0, 100), 200, 100)      # 200..300：只贴着印框上沿
    assert not _under_stain([big], mapper, (950, 1050), 300, 100)   # 列在印框左外侧
    assert not _under_stain([(1000, 300, 1900, 1200, np.ones((2, 2), np.uint8))], mapper, (0, 100), 300, 100)


def test_in_seal_counts_ink_on_the_small_seal_strokes_even_at_the_box_edge():
    """小印：格只有一角挨着印框，但格里的墨（列图）映回原图都落在印的笔画上 → 算印；格里另有墨（字）→ 不算。"""
    import numpy as np
    from types import SimpleNamespace as C
    from open_guji_cv.steps.row_segment import _in_seal
    H, W = 400, 400
    mask = np.zeros((H, W), np.uint8)
    mask[40:100, 240:300] = 1                                   # 原图左上原点
    img = np.full((100, 100), 255, np.uint8)                    # 列图：列图 (x, y) ↔ 原图左上 (x + 199, y)
    img[50:90, 51:91] = 0
    mapper = C(quad_tr=lambda x0, y0, x1, y1: [(200 - x0, y0), (200 - x1, y0), (200 - x1, y1), (200 - x0, y1)],
               to_page_tl=lambda x, y: (x + 199, y))
    f = _in_seal([(150, 0, 300, 300, mask)], mapper, img)
    cell = C(x0=0, x1=100, y0=0, y1=100)
    assert f(cell)
    img[50:90, 5:40] = 0                                        # 印外再加一块字的墨
    assert not f(cell)


def test_page_seals_reads_every_seal_from_the_seals_product():
    """印只来自印章定位 `seals` 产物（大印、小印都算）；大印没有笔画掩码；没有产物就是空表。"""
    from types import SimpleNamespace as C
    from open_guji_cv.steps.row_segment import _page_seals
    ps = C(height=3000, width=2300, seals=[C(kind="stain", template="", bbox=(300.0, 330.0, 1960.0, 1990.0))])
    ctx = C(has_product=lambda kind, page: page == 3, product=lambda kind, page: ps)
    assert _page_seals(ctx, 3) == [(300.0, 330.0, 1960.0, 1990.0, None)]
    assert _page_seals(ctx, 4) == []


def test_build_applies_layout_overrides(tmp_path):
    """`layout_overrides.jsonl`：只盖写到的字段，其余沿用 daizhige；表里没有的列整行补进来。"""
    dz = tmp_path / "corpus" / "daizhige"
    dz.mkdir(parents=True)
    rec = {"id": "0001-0010", "cols": [{"no": 0, "runs": [{"t": "text", "start": 2, "s": "甲乙"}]}]}
    (dz / "0001.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    pm = {"vol": "vol01", "page": 7, "kind": "text", "dzg_kind": "full", "dzg_id": "0001-0010", "side": 0}
    (dz / "page_map.jsonl").write_text(json.dumps(pm) + "\n", encoding="utf-8")
    ov = [{"vol": "vol01", "page": 7, "col": 1, "slots": [2, 3], "why": "图上从第 2 格起"},
          {"vol": "vol01", "page": 7, "col": 2, "slots": [-1, 1], "raised": 1, "why": "抬一格"},
          {"vol": "vol02", "page": 1, "col": 1, "slots": [1]}]
    (dz / "layout_overrides.jsonl").write_text(
        "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in ov), encoding="utf-8")
    rows = dl.build(tmp_path, {"vol01"})
    assert [(r["col"], r["slots"], r["raised"], r["dzg"]) for r in rows] == [
        (1, [2, 3], 0, "0001-0010h0"), (2, [-1, 1], 1, "override")]
    assert "why" not in rows[0]


def test_row_segment_refuses_book_missing_from_layout(tmp_path):
    """表在、开关开着、表里没有本册 → 报错，不悄悄当关（殿本 vol11–20 首跑，2026-10-23）。"""
    import json
    from open_guji_cv.steps import row_segment as RS
    p = tmp_path / "layout.jsonl"
    p.write_text(json.dumps({"vol": "vol04", "page": 23, "col": 1, "slots": [3], "notes": [], "half": [],
                             "raised": 0}) + "\n", encoding="utf-8")
    assert RS.load_layout(str(p), "vol11") == {}
    src = Path(RS.__file__).read_text(encoding="utf-8")
    assert "if p.layout_prior and not layout:" in src and "raise ValueError" in src
