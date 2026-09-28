# -*- coding: utf-8 -*-
"""`scripts/dzg_import.py`：daizhige 逐列整理本的转换与页对照（overview#195 P 道）。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "dzg_import", Path(__file__).resolve().parent.parent / "scripts" / "dzg_import.py")
dzg = importlib.util.module_from_spec(_SPEC)
sys.modules["dzg_import"] = dzg
_SPEC.loader.exec_module(dzg)

F = "　"


def _rec(rid, page, cols, roll="卷四", cover=False, pua_map=None):
    r = {"id": rid, "page": page, "cols": cols, "cover": cover, "geom": {"cap": 21, "ncol": 9},
         "roll": {"seq": 8, "name": roll}, "book": {"id": 1, "name": "欽定四庫全書總目"}}
    if pua_map:
        r["pua_map"] = pua_map
    return r


def _col(no, *runs):
    return {"no": no, "runs": list(runs)}


def test_column_line_keeps_start_and_note_structure():
    col = _col(3, {"t": "text", "start": 0, "s": "讀易私言一卷"},
               {"t": "note", "start": 6, "r": [[0, "兩江總督"]], "l": [[0, "採進本"]]})
    assert dzg.column_line(col) == "讀易私言一卷<兩江總督|採進本>"
    assert dzg.column_plain(col) == "讀易私言一卷兩江總督採進本"
    body = _col(4, {"t": "text", "start": 2, "s": "元許衡撰"})
    assert dzg.column_line(body) == F * 2 + "元許衡撰"


def test_column_line_fills_gaps_between_runs_and_inside_notes():
    col = _col(0, {"t": "text", "start": 1, "s": "甲"},
               {"t": "note", "start": 4, "r": [[0, "乙乙"], [3, "丙"]], "l": [[1, "丁"]]},
               {"t": "text", "start": 9, "s": "戊"})
    # 甲占第 1 格；小注从第 4 格起、宽 4 格（右行 乙乙　丙），戊在第 9 格
    assert dzg.column_line(col) == F + "甲" + F * 2 + "<乙乙" + F + "丙|" + F + "丁>" + F + "戊"


def test_raised_column_start_minus_one_has_no_padding():
    col = _col(0, {"t": "text", "start": -1, "s": "聖祖仁皇帝"})
    assert dzg.column_line(col) == "聖祖仁皇帝"


def test_fix_pua_maps_known_and_marks_unknown():
    s, miss = dzg.fix_pua("類", {"U+EF33": "𩔖"})
    assert s == "類𩔖〓" and miss == 1


def test_build_halves_splits_leaf_into_two_halves(tmp_path):
    cols = [_col(i, {"t": "text", "start": 2, "s": f"字{i}"}) for i in range(18)]
    p = tmp_path / "0001.jsonl"
    rows = [_rec("0001-0001", "1-1a", [], cover=True), _rec("0001-0002", "1-1b", cols)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    hs = dzg.build_halves([p])
    assert [(h.rid, h.side, len(h.cols)) for h in hs] == [
        ("0001-0001", 0, 0), ("0001-0001", 1, 0), ("0001-0002", 0, 9), ("0001-0002", 1, 9)]
    assert dzg.column_plain(hs[3].cols[0]) == "字9"
    lines, cols_out, stats = dzg.convert(hs)
    assert lines[1] == "#@ 0001-0002 1-1b h0"
    assert stats["columns"] == 18 and stats["empty_halves"] == 2
    assert cols_out[9]["col"] == 0 and cols_out[9]["side"] == 1


def test_repr_string_fields_are_parsed(tmp_path):
    r = _rec("0002-3389", "2-847b", [])
    r["cols"] = repr([_col(0, {"t": "text", "start": 0, "s": "唐鑑"})])
    p = tmp_path / "0002.jsonl"
    p.write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
    assert dzg.column_plain(dzg.build_halves([p])[0].cols[0]) == "唐鑑"


def test_align_segment_skips_plate_halves_and_pairs_blank_pages():
    # 我们：正文、卷末空页、正文；daizhige：正文、卷末空、牌记两个空半叶、正文
    pages = [(10, "text"), (11, "blank"), (12, "text")]
    hs = [(100, "full"), (101, "empty"), (102, "empty"), (103, "empty"), (104, "full")]
    pairs, cost = dzg.align_segment(pages, hs)
    got = dict(pairs)
    assert got[10] == 100 and got[12] == 104 and got[11] in (101, 102, 103)
    assert cost < 1


def test_align_segment_short_half_can_meet_ink_blank_page():
    # 「本也」两字的卷末页墨量低于空白阈值：仍应配上那个少字半叶
    pairs, _ = dzg.align_segment([(224, "blank"), (225, "blank")],
                                 [(1496, "short"), (1497, "empty")])
    assert dict(pairs) == {224: 1496, 225: 1497}


def test_align_segment_reports_missing_page_as_unpaired_half():
    pairs, cost = dzg.align_segment([(1, "text"), (2, "text")],
                                     [(10, "full"), (11, "full"), (12, "full")])
    assert len(pairs) == 2 and cost >= dzg.SKIP_HALF["full"]


def test_resolve_anchor_exact_and_nearest(tmp_path):
    cols = [_col(0, {"t": "text", "start": 0, "s": "欽定四庫全書總目卷四"})] + \
           [_col(i, {"t": "text", "start": 2, "s": "易本義附錄"}) for i in range(1, 18)]
    p = tmp_path / "0001.jsonl"
    p.write_text("\n".join(json.dumps(_rec(f"0001-{k:04d}", f"1-{k}a", cols), ensure_ascii=False)
                           for k in range(3)) + "\n", encoding="utf-8")
    hs = dzg.build_halves([p])
    assert dzg.resolve_anchor(hs, "易本義", expect=4) == 4
    try:
        dzg.resolve_anchor(hs, "=欽定四庫全書總目卷", expect=None)
    except ValueError:
        pass
    else:
        raise AssertionError("整列相等不该命中前缀")


def test_split_rolls_accepts_variant_title():
    lines = [("前言", {}), ("欽定四庫全書總目巻", {}), ("經部一", {}), ("欽定四庫全書總目卷二", {}), ("文", {})]
    got = dzg.split_rolls(lines)
    assert [t for t, _ in got] == ["(卷前)", "欽定四庫全書總目巻", "欽定四庫全書總目卷二"]


def test_compare_roll_counts_boundaries_and_missing_notes():
    a = [("讀易私言一卷", {"line": 1}), ("元許衡撰", {"line": 2})]
    b = [("讀易私言一卷兩江總督採進本", {"half": 0, "notes": ["兩江總督採進本"]}),
         ("元許衡撰", {"half": 0, "notes": []})]
    cols, diffs, *_ = dzg.compare_roll(a, b, None)
    assert cols["columns"] == 2 and cols["start_hit"] == 2 and cols["both_hit"] == 1
    assert [d["cat"] for d in diffs] == ["光盘缺小注"] and diffs[0]["dzg"] == "兩江總督採進本"
