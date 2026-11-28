"""切字 benchmark 打分（`eval/cut_bench`、`eval/cut_frame`、`eval/cut_ink`）：自造金标与产物，只验打分口径。"""
from __future__ import annotations

import json

import numpy as np

from open_guji_cv.eval import cut_bench, cut_frame, cut_ink


def _quad(x0, y0, x1, y1):
    return [[x1, y0], [x0, y0], [x0, y1], [x1, y1]]


def _bench(tmp_path, n_cols=4):
    """一册一页、n_cols 列、每列 3 格（格高 100）；第 1 列预测少一格（坏列），其余全对。"""
    b = tmp_path / "bench" / "bk"
    (b / "gold").mkdir(parents=True)
    (b / "bench.json").write_text(json.dumps({"book": "bk", "vols": {"01": {"pages": [5]}},
                                              "splits": {"random": {"01": [5]}}}))
    pred_cols = []
    with open(b / "gold" / "01-0005.jsonl", "w") as fh:
        for c in range(1, n_cols + 1):
            cells = [{"slot": s, "sub": None, "kind": "char", "quad": _quad(100 * c, 100 * s, 100 * c + 80, 100 * s + 100)}
                     for s in range(1, 4)]
            fh.write(json.dumps({"id": f"5:{c}", "vol": "01", "page": 5, "col": c, "label_origin": "human",
                                 "status": "active", "n": 3, "kinds": ["char"] * 3, "cells": cells}) + "\n")
            pc = [{"slot": x["slot"], "kind": "char", "quad_page": x["quad"]} for x in cells]
            pred_cols.append({"col": c, "cells": pc[:2] if c == 1 else pc})
    prod = tmp_path / "run" / "ws" / "products" / "01"
    (prod / "row_segment").mkdir(parents=True)
    (prod / "row_segment" / "p0005.json").write_text(json.dumps({"cells": {"page": 5, "columns": pred_cols}}))
    return b, prod


def test_score_dir_counts_and_sets(tmp_path):
    b, prod = _bench(tmp_path)
    r = cut_bench.score_dir(b, prod.parent)
    assert r["columns"] == 4 and r["L2_col_exact"] == 3 and r["L1_count_ok"] == 3
    assert r["by_set"]["random"]["columns"] == 4
    assert r["cols"]["01:5:1"]["exact"] is False


def test_gate_metrics_recall_and_false_alarm(tmp_path):
    b, prod = _bench(tmp_path)
    (prod / "cut_gate").mkdir()
    gm = {"page": 5, "admitted": True, "columns": [
        {"col": 1, "admitted": False, "reject": ["L1c 列宽"], "flags": []},    # 坏列被拦：检出
        {"col": 2, "admitted": True, "reject": [], "flags": ["L2b 噪点"]},      # 好列被打旗：误报（只算 any 档）
        {"col": 3, "admitted": True, "reject": [], "flags": []},
        {"col": 4, "admitted": True, "reject": [], "flags": []}]}
    rg = {"page": 5, "admitted": True, "columns": [{"col": 4, "admitted": True, "flags": [], "sliver_slots": [2]}]}
    (prod / "cut_gate" / "p0005.json").write_text(json.dumps({"gate_manifest": gm, "row_segment_gate_manifest": rg}))
    r = cut_bench.gate_metrics(b, prod.parent)
    assert (r["bad"], r["good"]) == (1, 3)
    assert r["tiers"]["block"]["recall"] == 1.0 and r["tiers"]["block"]["false_alarm_rate"] == 0.0
    assert r["tiers"]["any"]["hit_good"] == 2                       # 列 2 旗、列 4 碎格
    assert {x["col"] for x in r["false_alarm"]} == {"01:5:2", "01:5:4"}


def test_gate_metrics_skips_pages_without_gate(tmp_path):
    b, prod = _bench(tmp_path)
    r = cut_bench.gate_metrics(b, prod.parent)
    assert r["columns"] == 0 and r["pages_no_gate"] == ["01:5"]


def test_cut_frame_judge_and_flips():
    gold = [10, 10, 50, 60]
    assert cut_frame.judge([10, 10, 50, 60], gold, 2)["iou_ok"]
    j = cut_frame.judge([10, 15, 50, 60], gold, 2)        # 上边往里收 5px：切笔
    assert j["cut"] and not j["junk"]
    j = cut_frame.judge([5, 10, 50, 60], gold, 2)         # 左边往外扩 5px：带渣
    assert j["junk"] and not j["cut"]
    assert cut_frame.judge(None, gold, 2)["missing"]
    items = [{"key": "k1", "book": "bk", "vol": "01", "page": 1, "col": 1, "slot": 2, "sub": None,
              "tight": gold, "status": "ok", "split": "tune", "tags": []}]
    a = cut_frame.score(items, {("01", 1, 1, 2, None): [10, 10, 50, 60]})
    b = cut_frame.score(items, {("01", 1, 1, 2, None): [10, 15, 50, 60]})
    assert a["groups"]["all"]["cut"] == 0 and b["groups"]["all"]["cut"] == 1
    fl = cut_frame.flips(a, b)
    assert len(fl) == 1 and fl[0]["worse"]


def test_clean_ink_box():
    W, H = 200, 300
    ink = np.zeros((H, W), bool)
    ink[120:170, 60:90] = True                            # 格内一笔：干净
    quad = _quad(W - 120, 100, W - 40, 200)                # 页坐标（x 从右量）：图像 x 40–120
    box, why = cut_ink.clean_ink_box(ink, W, quad)
    assert why == "ok" and box == [W - 90.0, 120.0, W - 60.0, 170.0]
    ink[190:230, 70:75] = True                            # 跨下格界：不干净
    assert cut_ink.clean_ink_box(ink, W, quad) == (None, "跨格界")
