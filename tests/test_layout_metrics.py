# -*- coding: utf-8 -*-
"""版面评测指标（eval/layout_metrics.py、layout_gold.py）：全用自造数据。"""
from __future__ import annotations

import copy

import pytest

from open_guji_cv.eval import layout_gold as lg
from open_guji_cv.eval import layout_metrics as lm

W, H, PITCH = 2000, 3000, 180.0


def _doc(n=10, x_right=1900.0, slope=0.01, **kw):
    vl = []
    for i in range(n):
        x0 = x_right - i * PITCH
        vl.append({"pts": [[x0 + slope * y, y] for y in (300.0, 1500.0, 2700.0)],
                   "state": "intact", "gaps": []})
    d = {"width": W, "height": H, "vlines": vl,
         "top": {"pts": [[0.0, 300.0], [W - 1.0, 300.0]]},
         "bottom": {"pts": [[0.0, 2700.0], [W - 1.0, 2700.0]]},
         "n_cols": n - 1, "rows_per_col": None, "page_type": "body", "policy": "standard", "tags": []}
    d.update(kw)
    return d


def test_gold_pitch():
    assert lm.gold_pitch(_doc()) == pytest.approx(PITCH, rel=0.02)


def test_perfect_prediction():
    g = _doc()
    r = lm.page_metrics(g, copy.deepcopy(g))
    s = lm.aggregate([r])["all"]
    assert s["recall@0.02"] == 1.0 and s["precision@0.02"] == 1.0
    assert s["line_p95_px"]["max"] == pytest.approx(0.0, abs=1e-6)
    assert s["n_cols_acc"] == 1.0 and s["policy"]["wrong_skip"] == 0


def test_shift_counts_by_tolerance():
    g = _doc()
    p = copy.deepcopy(g)
    for v in p["vlines"]:
        for pt in v["pts"]:
            pt[0] += 0.04 * PITCH          # 偏 7.2px
    s = lm.aggregate([lm.page_metrics(g, p)])["all"]
    assert s["recall@0.02"] == 0.0          # 严格容差不过
    assert s["recall@0.05"] == 1.0
    assert s["line_p95_px"]["median"] == pytest.approx(0.04 * PITCH, rel=0.01)


def test_missed_and_extra_lines():
    g = _doc()
    p = copy.deepcopy(g)
    del p["vlines"][3]                      # 漏一条
    p["vlines"].append({"pts": [[50.0, 300.0], [50.0, 2700.0]], "state": "intact", "gaps": []})
    s = lm.aggregate([lm.page_metrics(g, p)])["all"]
    assert s["lines_gold"] == 10 and s["lines_matched"] == 9
    assert s["recall@0.05"] == pytest.approx(0.9)
    assert s["precision@0.05"] == pytest.approx(0.9)    # 10 条预测里 9 条命中


def test_broken_line_gap_error_split():
    g = _doc()
    g["vlines"][4]["state"] = "broken"
    g["vlines"][4]["gaps"] = [[1000.0, 1800.0]]
    p = copy.deepcopy(g)
    # 预测线在断口里被拉直插值，偏 20px；实线区间贴合
    pts = p["vlines"][4]["pts"]
    p["vlines"][4]["pts"] = [pts[0], [pts[1][0] + 20.0, 1400.0], pts[2]]
    r = lm.page_metrics(g, p)
    s = lm.aggregate([r])["all"]
    assert s["broken"]["gold_lines"] == 1 and s["broken"]["matched"] == 1
    assert s["gap_err_px"]["n"] > 0 and s["gap_err_px"]["p95"] > 5.0


def test_frame_policy_and_cols():
    g = _doc(rows_per_col=[21] * 9)
    p = copy.deepcopy(g)
    p["top"]["pts"] = [[0.0, 310.0], [W - 1.0, 310.0]]
    p["policy"], p["n_cols"] = "skip", 8
    p["rows_per_col"] = [21] * 8 + [20]
    s = lm.aggregate([lm.page_metrics(g, p)])["all"]
    assert s["top_frame_px"]["median"] == pytest.approx(10.0)
    assert s["bottom_frame_px"]["median"] == pytest.approx(0.0)
    assert s["policy"]["wrong_skip"] == 1 and s["policy"]["acc"] == 0.0
    assert s["n_cols_acc"] == 0.0
    assert s["rows_acc"] == pytest.approx(8 / 9)


def test_aggregate_by_tags_and_worst():
    g1, g2 = _doc(tags=["faint"], book="a"), _doc(tags=[], book="b")
    p2 = copy.deepcopy(g2)
    p2["vlines"] = p2["vlines"][:-1]
    r1, r2 = lm.page_metrics(g1, copy.deepcopy(g1)), lm.page_metrics(g2, p2)
    agg = lm.aggregate([r1, r2], key="tags")
    assert agg["faint"]["pages"] == 1 and agg["all"]["pages"] == 2
    assert lm.aggregate([r1, r2], key="book")["b"]["recall@0.05"] == pytest.approx(0.9)
    assert lm.worst_pages([("a", r1), ("b", r2)], 1)[0][0] == "b"


def test_validate_doc():
    assert lg.validate_doc(_doc()) == []
    g = _doc()
    g["vlines"][2]["state"] = "broken"        # 没写 gaps
    g["vlines"][0]["pts"][0][0] = W + 100     # 出界
    g["vlines"].reverse()                     # 乱序
    bad = "\n".join(lg.validate_doc(g))
    assert "gaps" in bad and "图外" in bad and "从右到左" in bad


def test_page_geometry_adapter_dedupes():
    item = {"status": "active", "anchor": {"book": "vol01", "page": 7},
            "expected": {"band_ys": [700.0, 1500.0, 2300.0], "n_cols": 2,
                         "image_size": {"width": W, "height": H},
                         "rules": [{"kind": "rule", "x_top": 300.0, "x_mid": 298.0, "x_bot": 296.0},
                                   {"kind": "rule", "x_top": 500.0, "x_mid": 498.0, "x_bot": 496.0},
                                   {"kind": "rule", "x_top": 500.5, "x_mid": 498.5, "x_bot": 496.5},
                                   {"kind": "rule", "x_top": 700.0, "x_mid": 698.0, "x_bot": 696.0}]}}
    stale = {**item, "status": "stale"}
    out = lg.docs_from_page_geometry([item, stale])
    assert len(out) == 1 and out[0][0] == "vol01/7"
    doc = out[0][1]
    assert len(doc["vlines"]) == 3                            # 重复的一条合并
    assert doc["vlines"][0]["pts"][0][0] > doc["vlines"][-1]["pts"][0][0]   # 右→左
    assert lg.validate_doc(doc) == []


def test_page_type_adapter_policy():
    items = [{"status": "active", "anchor": {"book": "vol01", "page": p}, "expected": {"page_type": t}}
             for p, t in ((1, "cover"), (3, "body"), (5, "toc"))]
    d = lg.docs_from_page_type(items)
    assert [d[f"vol01/{p}"]["policy"] for p in (1, 3, 5)] == ["skip", "standard", "standard"]


def test_doc_from_borders_roundtrip():
    """右上原点的产物 → 左上原点的文档：竖线应右→左排，x 换算正确。"""
    b = {"width": W, "height": H, "expected_cols": 2,
         "top": {"y_at_right": 300.0, "slope": 0.0, "kind": "top"},
         "bottom": {"y_at_right": 2700.0, "slope": 0.0, "kind": "bottom"},
         "verticals": [{"x_at_top": 100.0 + i * 180.0, "slope": 0.0} for i in range(3)]}
    d = lg.doc_from_borders(b, {"page_type": "body", "page_type_policy": "standard", "n_cols": 2})
    xs = [v["pts"][0][0] for v in d["vlines"]]
    assert xs == pytest.approx([W - 1 - 100.0, W - 1 - 280.0, W - 1 - 460.0])
    assert d["policy"] == "standard" and d["n_cols"] == 2
    assert lg.validate_doc(d) == []


def test_health_flags_bad_pages():
    good = _doc()
    h = lm.health(good, expected_cols=9)
    assert h["n_cols_ok"] is True and h["pitch_cv"] < 0.01 and h["inside"] and h["frame_ok"]
    bad = copy.deepcopy(good)
    del bad["vlines"][4]                       # 漏线：列数不对、列距出现双倍间隔
    hb = lm.health(bad, expected_cols=9)
    assert hb["n_cols_ok"] is False and hb["pitch_dev_max"] > 0.5
    assert lm.summarize_health([h, hb])["n_cols_ok"] == 0.5


def test_bench_run_reads_products(tmp_path):
    import json
    from open_guji_cv.eval import layout_bench as lb
    b = {"width": W, "height": H, "expected_cols": 2,
         "top": {"y_at_right": 300.0, "slope": 0.0, "kind": "top"},
         "bottom": {"y_at_right": 2700.0, "slope": 0.0, "kind": "bottom"},
         "verticals": [{"x_at_top": 100.0 + i * 180.0, "slope": 0.0} for i in range(3)]}
    (tmp_path / "bk" / "border_detect").mkdir(parents=True)
    (tmp_path / "bk" / "border_detect_gate").mkdir(parents=True)
    (tmp_path / "bk" / "border_detect" / "p0007.json").write_text(json.dumps({"borders": b}))
    (tmp_path / "bk" / "border_detect_gate" / "p0007.json").write_text(json.dumps(
        {"border_detect_gate_manifest": {"page_type": "toc", "page_type_policy": "standard", "n_cols": 2}}))
    pt = [{"status": "active", "anchor": {"book": "bk", "page": 3}, "expected": {"page_type": "toc"}},
          {"status": "active", "anchor": {"book": "bk", "page": 4}, "expected": {"page_type": "cover"}}]
    rep = lb.run(tmp_path, "bk", expected_cols=2, pt_items=pt, page_map={"bk/3": {"new": 7}})
    assert rep["pages_run"] == 1 and rep["health"]["n_cols_ok"] == 1.0
    assert rep["page_type"]["pages"] == 1 and rep["page_type"]["all"]["acc"] == 1.0   # cover 无对应页，略过
    assert lb.parse_pages("1-3,7") == {1, 2, 3, 7}


def test_frame_errors_kind_and_outer():
    from open_guji_cv.eval import layout_metrics as lm
    g = {"frame": {"top": {"kind": "double", "outer": {"pts": [[0, 10], [100, 10]]}},
                   "bottom": {"kind": "single", "outer": None},
                   "left": {"kind": "double", "outer": {"pts": [[5, 0], [5, 100]]}}}}
    p = {"frame": {"top": {"kind": "double", "outer": {"pts": [[0, 14], [100, 14]]}},
                   "bottom": {"kind": "double", "outer": {"pts": [[0, 90], [100, 90]]}},
                   "left": {"kind": "none", "outer": None}}}
    r = lm.frame_errors(g, p)
    assert r["top"]["ok"] and abs(r["top"]["outer"]["med"] - 4) < 1e-6
    assert not r["bottom"]["ok"] and r["bottom"]["outer"] is None
    assert not r["left"]["ok"]
    assert lm.frame_errors({}, p) is None


def test_doc_from_borders_head_raise_polyline():
    """抬头列：上内框/上外框在该列两条界行之间是阶梯折线（同 x 两点表示台阶），其余列仍是主框。"""
    b = {"width": W, "height": H, "expected_cols": 3,
         "top": {"y_at_right": 300.0, "slope": 0.0, "kind": "top"},
         "bottom": {"y_at_right": 2700.0, "slope": 0.0, "kind": "bottom"},
         "top_frame_kind": "double", "top_outer_offset": -30.0,
         "verticals": [{"x_at_top": 100.0 + i * 180.0, "slope": 0.0} for i in range(4)],
         "head_raise": [{"col": 2, "inner_y": 150.0, "outer_y": 100.0, "estimated": False}]}
    d = lg.doc_from_borders(b)
    # 第 2 列在产物坐标 x∈[280,460]，换成左上原点 [W-1-460, W-1-280]
    a, c = W - 1 - 460.0, W - 1 - 280.0
    top = lm._pts(d["top"])
    assert lm.y_at(top, [(a + c) / 2])[0] == pytest.approx(150.0)
    assert lm.y_at(top, [a - 50.0])[0] == pytest.approx(300.0)
    outer = lm._pts(d["frame"]["top"]["outer"])
    assert lm.y_at(outer, [(a + c) / 2])[0] == pytest.approx(100.0)
    # 外框台阶竖边在内框竖边外侧，让出内外间距 50 px
    assert lm.y_at(outer, [a - 20.0])[0] == pytest.approx(100.0)
    assert lm.y_at(outer, [c + 20.0])[0] == pytest.approx(100.0)
    assert lm.y_at(outer, [a - 80.0])[0] == pytest.approx(270.0)
    assert lg.validate_doc(d) == []


def test_doc_from_borders_no_head_raise_unchanged():
    b = {"width": W, "height": H, "expected_cols": 2,
         "top": {"y_at_right": 300.0, "slope": 0.0, "kind": "top"},
         "bottom": {"y_at_right": 2700.0, "slope": 0.0, "kind": "bottom"},
         "verticals": [{"x_at_top": 100.0 + i * 180.0, "slope": 0.0} for i in range(3)]}
    d = lg.doc_from_borders(b)
    assert len(d["top"]["pts"]) == 24 and {p[1] for p in d["top"]["pts"]} == {300.0}
