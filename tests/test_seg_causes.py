"""review/seg_causes：S 类待审成因归因（只读产物包）。"""
import json

from open_guji_cv.review import seg_causes as S


def _w(root, step, page, key, data):
    d = root / step
    d.mkdir(parents=True, exist_ok=True)
    (d / f"p{page:04d}.json").write_text(json.dumps({key: data}, ensure_ascii=False), encoding="utf-8")


def _page(root, page, *, note="", coord=True, fallback=None, seals=(), page_type="body", n_slots=(21, 21),
          bounds=None):
    cols = [1, 2]
    _w(root, "align_ref", page, "align_ref", {
        "note": note, "chars": [],
        "coord": [{"id": f"b:{page}:{c}:{s}", "ref_char": "字"} for c in cols for s in (1, 2)] if coord else [],
        "coord_cols": cols if coord else [], "coord_fallback": fallback or {}})
    _w(root, "border_detect_gate", page, "border_detect_gate_manifest",
       {"admitted": True, "page_type": page_type, "flags": [], "reject": [], "n_cols": 2, "expected_cols": 2})
    _w(root, "row_segment_gate", page, "row_segment_gate_manifest", {"admitted": True, "reject": [], "columns": []})
    _w(root, "seal_detect", page, "seals", {"seals": list(seals)})
    _w(root, "invert_detect", page, "inverted", {"bands": []})
    _w(root, "row_segment", page, "cells", {"columns": [
        {"col": c, "n_body_slots": n, "period": 100.0, "error": None,
         "boundaries": bounds if (bounds and c == 2) else [0, 100, 200, 300, 400]}
        for c, n in zip(cols, n_slots)]})
    _w(root, "cell_shrink", page, "char_index", {"columns": [
        {"col": c, "chars": [{"patch_key": "k", "cell_type": "char"} for _ in (1, 2)]} for c in cols]})


def _cause(root, page, col=1, reason="seg_page_unaligned", known=None):
    return S.attribute(S.page_facts(root, page, known), col, reason)[0]


def test_priority_and_flags(tmp_path):
    _page(tmp_path, 1, note="8-gram 锚定失败；钉页 dzg:null（整理本无此页）", coord=False)
    _page(tmp_path, 2)                                                       # 每列都配上整理本
    _page(tmp_path, 3, coord=False, seals=[{"kind": "stain", "source": "frame"}])
    _page(tmp_path, 4, fallback={"2": "格数少于整理本字数（20 < 21）"})
    _page(tmp_path, 5, fallback={"2": "与现役对位冲突（…）"}, page_type="table")
    _page(tmp_path, 6, fallback={"1": "列行对应不成立"}, bounds=[0, 100, 130, 300, 400])
    assert _cause(tmp_path, 1) == "pinned"
    assert S.attribute(S.page_facts(tmp_path, 1), 1, "x")[1] == ["pinned", "ref_none"]
    assert _cause(tmp_path, 2) == "grid_ok"
    assert _cause(tmp_path, 2, known="图源断烂") == "known"
    assert _cause(tmp_path, 3) == "ref_none"
    _page(tmp_path, 3, seals=[{"kind": "stain", "source": "frame"}], fallback={"1": "x"})
    assert _cause(tmp_path, 3) == "seal_stain"
    assert _cause(tmp_path, 4, col=2) == "slot_short"
    assert _cause(tmp_path, 4, col=1) == "none"
    assert _cause(tmp_path, 5, col=2) == "page_kind"
    assert _cause(tmp_path, 6, col=2) == "row_height"
    assert _cause(tmp_path, 6, col=1) == "coord_other"
    assert _cause(tmp_path, 6, col=1, reason="seg_defect") == "seg_defect"


def test_run_with_pending_list_and_summary(tmp_path):
    prod = tmp_path / "prod"
    _page(prod / "b", 4, fallback={"2": "格数少于整理本字数（20 < 21）"})
    pend = tmp_path / "x.pending.json"
    pend.write_text(json.dumps({"cells": [
        {"cell": "b:4:2:3", "pending_reason": "seg_col_unaligned"},
        {"cell": "4:1:1", "pending_reason": "seg_page_unaligned"},
        {"cell": "b:4:1:2", "pending_reason": "group_abstain"},
    ]}), encoding="utf-8")
    rows = S.run(["b"], prod, [pend])
    assert [(r["格号"], r["成因"]) for r in rows] == [("b:4:2:3", "slot_short"), ("b:4:1:1", "none")]
    assert len(S.run(["b"], prod, [pend], all_reasons=True)) == 3
    md = S.summary_md(rows, ["b"], "单")
    assert "slot_short 格少于整理本 | 1 | 1 | 0/1/0/0" in md
    pages = S.by_page(rows)
    assert pages[0]["主成因"].startswith("slot_short=1") and pages[0]["格数"] == 2


def test_known_file(tmp_path):
    k = tmp_path / "k.tsv"
    k.write_text("# 注释\nvol44:236\t图源断烂\n212\t\n", encoding="utf-8")
    assert S.load_known(k, ["vol44"]) == {("vol44", 236): "图源断烂", ("vol44", 212): "已答复"}


def test_roster_page_is_page_kind(tmp_path):
    """职名页（row_segment 列 flags 带 roster）归特殊页型，不当格数离群（史記 01 册职名页，11-04）。"""
    _page(tmp_path, 7, fallback={"2": "x"}, n_slots=(21, 30))
    p = tmp_path / "row_segment" / "p0007.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for c in d["cells"]["columns"]:
        c["flags"] = ["roster"]
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert _cause(tmp_path, 7, col=2) == "page_kind"
