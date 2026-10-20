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
