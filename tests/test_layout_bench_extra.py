"""版面三个 bench 的口径（自造数据）：layout_bench 按套书汇总、survey_bench（1a）、seal_bench（1c）。"""
from __future__ import annotations

import json

from open_guji_cv.eval import layout_bench as lb
from open_guji_cv.eval import seal_bench as sb
from open_guji_cv.eval import survey_bench as vb


def _doc(xs, w=1000, h=1500):
    return {"width": w, "height": h, "vlines": [{"pts": [[x, 0], [x, h]], "state": "intact", "gaps": []} for x in xs],
            "top": {"pts": [[0, 50], [w, 50]]}, "bottom": {"pts": [[0, h - 50], [w, h - 50]]},
            "n_cols": len(xs) - 1, "page_type": "body", "policy": "standard"}


def _write_pred(root, book, page, xs):
    d = root / book / "border_detect"
    d.mkdir(parents=True, exist_ok=True)
    borders = {"vlines": [{"pts": [[x, 0], [x, 1500]]} for x in xs]}
    (d / f"p{page:04d}.json").write_text(json.dumps({"borders": borders}), encoding="utf-8")


def test_series_of_and_buckets():
    assert [lb.series_of(b) for b in ("vol01", "sj05", "qtw190", "mj03", "zz9")] == ["殿本", "史記", "全唐文", "脈經", None]
    # 偏差分档：6px 只进 >5，12px 进 >5 与 >10，25px 三档全进
    g = _doc([900, 700, 500, 300, 100])
    items = [{"id": "vol01:1", "anchor": {"book": "vol01", "page": 1}, "status": "active", "expected": g}]
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _write_pred(td, "vol01", 1, [906, 712, 525, 300, 100])
        _orig = lb.pred_doc
        lb.pred_doc = lambda products, b, p, ec=None: _doc([906, 712, 525, 300, 100])
        try:
            rep = lb.run_series(td, items)
        finally:
            lb.pred_doc = _orig
    a = rep["series"]["殿本"]
    assert a["line_gt_px"] == {">5": 3, ">10": 2, ">20": 1}
    md = lb.series_markdown(rep)
    assert "| 殿本 | 1 |" in md and "| 史記 | 无金标页" in md


def test_survey_bench_flags_odd_pages_and_false_alarm():
    base = lambda pg, w=1800, h=2600: {"id": f"b1:{pg}", "anchor": {"book": "b1", "page": pg}, "status": "active",
                                       "input": {"width": w, "height": h}, "label_origin": "human",
                                       "expected": {"odd": False, "kind": None}}
    items = [base(i) for i in range(1, 6)]
    wide = base(6, 3700, 2600)
    wide["expected"] = {"odd": True, "kind": "双叶横拼(1×2)"}
    items.append(wide)
    rep = vb.run(items)
    s = rep["summary"]["human/全部"]
    assert s["recall"] == 1.0 and s["false_alarm"] == 0 and s["kind_acc"] == 1.0
    assert rep["flips"] == []
    # 把正常页预期标成异常再把宽页标成正常：两处翻转，且有漏报与误报
    items[0]["expected"] = {"odd": True, "kind": "偏小(标签/残页)"}
    wide["expected"] = {"odd": False, "kind": None}
    rep = vb.run(items)
    assert set(rep["flips"]) == {"b1:1", "b1:6"}
    assert rep["summary"]["human/全部"]["false_alarm"] == 1


def test_survey_bench_skips_books_with_few_pages():
    items = [{"id": f"b2:{i}", "anchor": {"book": "b2", "page": i}, "input": {"width": 10, "height": 10},
              "expected": {"odd": False, "kind": None}} for i in (1, 2)]
    assert vb.run(items)["skipped_books"] == ["b2"]


def test_seal_iou_match_and_draft_excluded(tmp_path):
    assert sb.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert sb.iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    d = tmp_path / "mj01" / "seal_detect"
    d.mkdir(parents=True)
    (d / "p0003.json").write_text(json.dumps({"seals": {"page": 3, "width": 1, "height": 1, "seals": [
        {"kind": "crisp", "bbox": [0, 0, 100, 100], "score": 1, "source": "template"}]}}), encoding="utf-8")
    items = [
        {"id": "mj01:3", "anchor": {"book": "mj01", "page": 3}, "label_origin": "human",
         "expected": {"seals": [{"kind": "crisp", "bbox": [10, 10, 100, 100]}, {"kind": "stain", "bbox": [500, 500, 600, 600]}]}},
        {"id": "mj01:9", "anchor": {"book": "mj01", "page": 9}, "label_origin": "draft", "expected": {"seals": []}},
    ]
    rep = sb.run(tmp_path, items)
    s = rep["summary"]["脈經"]
    assert s["matched"] == 1 and s["gold_seals"] == 2 and s["missed_seals"] == ["mj01:3#1"]
    assert s["kind_acc"] == 1.0 and s["precision@iou0.5"] == 1.0
    assert rep["pending_draft"] == ["mj01:9"]


# ── 统一接口（eval/benches/layout.py）──────────────────────────────

def test_layout_benches_registered_and_alias_mapping():
    from open_guji_cv.eval import bench as B
    from open_guji_cv.eval.benches import layout as L
    ids = {s.id for s in B.all_specs()}
    assert {"layout", "page-survey", "seal-box"} <= ids
    assert [L.vol_of(a) for a in ("vol01", "sj05", "qtw005", "mj01", "mj03")] == ["vol01", "05", "005", "1", "03"]
    assert B.get("layout").gold_rel("siku-zongmu") == "layout/items.jsonl"


def _gold_file(tmp_path, rows):
    p = tmp_path / "items.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def test_layout_plan_and_score(tmp_path, monkeypatch):
    from open_guji_cv.eval import bench as B
    from open_guji_cv.eval.benches import layout as L
    g = _doc([900, 700, 500, 300, 100])
    rows = [{"id": "sj05:3", "anchor": {"book": "sj05", "page": 3}, "status": "active", "expected": g},
            {"id": "sj20:4", "anchor": {"book": "sj20", "page": 4}, "status": "active", "expected": g},
            {"id": "vol01:9", "anchor": {"book": "vol01", "page": 9}, "status": "active", "expected": g}]
    gold = _gold_file(tmp_path, rows)
    assert L.plan_layout(gold, "988g3f0wsu", []) == {"05": [3], "20": [4]}
    assert L.plan_layout(gold, "988g3f0wsu", ["20"]) == {"20": [4]}
    assert L.plan_layout(gold, "siku-zongmu", []) == {"vol01": [9]}
    # 预测：第一页一条线偏 12px，第二页全对
    docs = {("05", 3): _doc([912, 700, 500, 300, 100]), ("20", 4): g}
    monkeypatch.setattr(lb, "pred_doc", lambda products, v, p, ec=None: docs.get((v, p)))
    ctx = B.BenchCtx("988g3f0wsu", [], tmp_path, {"gold": str(gold)})
    r = L.score_layout(ctx, tmp_path)
    assert r.metrics["lines_gold"] == 10 and r.metrics["lines_gt5px"] == 1 and r.metrics["lines_gt10px"] == 1
    assert r.metrics["line_ok_rate"] == 0.9 and r.metrics["lines_missed"] == 0
    assert {i["id"]: i["ok"] for i in r.items} == {"sj05:3": False, "sj20:4": True}


def test_survey_and_seal_benches_report_no_gold_properly(tmp_path):
    from open_guji_cv.eval import bench as B
    from open_guji_cv.eval.benches import layout as L
    rows = [{"id": "mj01:3", "anchor": {"book": "mj01", "page": 3}, "label_origin": "draft", "status": "active",
             "expected": {"seals": []}}]
    gold = _gold_file(tmp_path, rows)
    assert L.plan_seal(gold, "99k3i35yww", []) == {}                     # 只有待核底稿＝没金标
    base = lambda pg, w=1800: {"id": f"mj01:{pg}", "anchor": {"book": "mj01", "page": pg}, "status": "active",
                               "input": {"width": w, "height": 2600}, "label_origin": "rule",
                               "expected": {"odd": False, "kind": None}}
    sg = _gold_file(tmp_path, [base(i) for i in range(1, 6)])
    ctx = B.BenchCtx("99k3i35yww", [], tmp_path, {"gold": str(sg)})
    r = L.score_survey(ctx, L.run_survey(ctx))
    assert r.metrics["agree"] == 1.0 and r.metrics["false_alarm"] == 0 and "rule" in r.reason
    # 经 execute 跑一遍并对自己：翻转为 0
    spec = B.get("page-survey")
    r1 = B.execute(spec, ctx)
    out = B.write_result(tmp_path / "r1", r1)
    r2 = B.execute(spec, ctx, against=out)
    assert r2.metrics["flip_worse"] == 0 and r2.status == "ok"
