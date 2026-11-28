"""第三步识字 bench（eval/benches/read.py）的打分口径：自造脚本输出与分片，不跑脚本、不碰真书数据。"""
from __future__ import annotations

import json

from open_guji_cv.eval import bench as B
from open_guji_cv.eval.benches import read as R


def _ctx(tmp_path, book=R.SIKU, gold=None, guards=None, args=None):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    ds = tmp_path / "ds"
    (ds / "guards").mkdir(parents=True, exist_ok=True)
    if guards is not None:
        import yaml
        (ds / "guards" / "read.yaml").write_text(yaml.safe_dump({"guards": guards}, allow_unicode=True), encoding="utf-8")
    res = {"dataset": str(ds)}
    if gold is not None:
        res["gold"] = str(gold)
    return B.BenchCtx(book, [], work, res, args=args or {}, env={"cv": "t"})


def _jsonl(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _advset_out(way="cov", near_bad=("q1",), var_bad=()):
    return {"sim_model": None, "headline": {"way": way, "near_false_same": len(near_bad), "near_false_same_rate": len(near_bad) / 3,
                                             "variant_false_same": len(var_bad)},
            "result": {way: {"形近": {"n_query": 3, "partner_false_same": 0, "by_split": {"dev": 0, "test": len(near_bad)}},
                             "异体": {"n_query": 1}}},
            "flips": {f"{way}|形近": [f"{q}|甲→乙|c9" for q in near_bad], f"{way}|异体": [f"{q}|甲→丙|c8" for q in var_bad]}}


def test_registered_and_suites():
    ids = {s.id for s in B.all_specs()}
    assert {"read-3a-advset", "read-3a-damaged", "read-3b-near"} <= ids
    assert {s.id for s in B.expand(["@read-3a"])} == {"read-3a-advset", "read-3a-damaged", "read-3a-pairs", "read-normalize"}
    s = B.get("read-3a-advset")
    assert s.gold_rel("995ejelvk0") == "glyph-match/advset-qtw" and s.gold_rel("99k3i35yww") is None
    assert B.get("read-3a-damaged").gold_rel("995ejelvk0") is None        # 全唐文没有残损集 → no_gold


def test_advset_items_and_dataset_guard(tmp_path):
    gold = tmp_path / "g"
    _jsonl(gold / "items.jsonl", [{"query_id": q} for q in ("q1", "q2", "q3", "q2")])
    pred = tmp_path / "advset.json"
    pred.write_text(json.dumps(_advset_out(var_bad=("q3",)), ensure_ascii=False), encoding="utf-8")
    g = [{"bench": "read-3a-advset", "ws": R.SIKU, "metric": "形近误认", "dir": "max", "limit": 0},
         {"bench": "read-3a-advset", "ws": "988g3f0wsu", "metric": "形近误认", "dir": "max", "limit": 9},
         {"bench": "read-3a-damaged", "ws": R.SIKU, "metric": "误放", "dir": "max", "limit": 0}]
    ctx = _ctx(tmp_path, gold=gold, guards=g)
    r = R.advset_score(ctx, pred)
    assert r.metrics["形近误认"] == 1 and r.n == 3
    assert [(x["id"], x["ok"], x["variant_same"]) for x in r.items] == [("q1", False, False), ("q2", True, False),
                                                                        ("q3", True, True)]
    assert r.status == "regressed" and [x["metric"] for x in r.guards] == ["形近误认"]   # 只取本 bench、本书那条
    ctx.book = "988g3f0wsu"
    assert R.advset_score(ctx, pred).status == "ok"


def test_missing_metric_is_not_a_pass(tmp_path):
    gold = tmp_path / "g"
    _jsonl(gold / "items.jsonl", [{"query_id": "q1"}])
    pred = tmp_path / "advset.json"
    pred.write_text(json.dumps(_advset_out(), ensure_ascii=False), encoding="utf-8")
    ctx = _ctx(tmp_path, gold=gold, guards=[{"bench": "read-3a-advset", "ws": R.SIKU, "metric": "没这个",
                                             "dir": "max", "limit": 5}])
    r = R.advset_score(ctx, pred)
    assert r.status == "regressed" and r.guards[0]["status"] == "unverified"


def test_damaged_items(tmp_path):
    gold = tmp_path / "g"
    _jsonl(gold / "items.jsonl", [{"query_id": "a", "kind": "残笔"}, {"query_id": "b", "kind": "细笔"},
                                  {"query_id": "c", "kind": "对照"}])
    way = "cov"
    pred = tmp_path / "mp.json"
    pred.write_text(json.dumps({"headline": {"way": way, "false_same": 1},
                                "result": {way: {"全部": {"n": 3, "rank1_rate": 1 / 3, "accept_rate": 1 / 3}}},
                                "flips": {way: ["a|甲→乙（误放）", "b|甲→丙"]}}, ensure_ascii=False), encoding="utf-8")
    r = R.damaged_score(_ctx(tmp_path, gold=gold, guards=[]), pred)
    assert r.metrics["误放"] == 1 and r.metrics["全部 首位"] == 33.33
    assert [(x["id"], x["ok"], x["false_same"]) for x in r.items] == [("a", False, True), ("b", False, False),
                                                                     ("c", True, False)]


def test_near_score_and_plan(tmp_path):
    gold = tmp_path / "bench3b"
    gold.mkdir()
    (gold / "bench.json").write_text(json.dumps({"books": {"96mid1ogzk": {"ws": R.SIKU, "vols": {
        "vol04": {"role": "test"}, "vol06": {"role": "fit"}}}}}), encoding="utf-8")
    assert R.near_plan(gold, R.SIKU, []) == {"vol04": None}
    assert R.near_plan(gold, "988g3f0wsu", []) == {}
    ctx = _ctx(tmp_path, gold=gold, guards=[])
    _jsonl(ctx.work / "near-rows.jsonl", [{"id": "96mid1ogzk:gong:cnn_small:c1", "ok": True},
                                          {"id": "96mid1ogzk:gong:cnn_small:c2", "ok": False, "wrong": True}])
    pred = tmp_path / "near.json"
    pred.write_text(json.dumps({"books": {"96mid1ogzk": {"models": {"cnn_small:gong": {"fingerprint": "x"},
                                                                    "rr_shape:rr": {"error": "missing_model"}},
                                                         "skipped_methods": []}},
                                "headline": [{"method": "cnn_small", "group": "gong", "decided": 2, "right": 1, "wrong": 1,
                                              "triggered": 5, "coverage": {"rate": 0.5}}],
                                "methods_sha": {"96mid1ogzk": "s"}}), encoding="utf-8")
    r = B.apply_guards(B.get("read-3b-near"), R.near_score(ctx, pred))
    assert r.metrics["组内误判"] == 1 and r.metrics["准确率"] == 50.0 and r.metrics["缺模型"] == 1
    assert r.metrics["by_method"]["cnn_small:gong"]["coverage"] == 0.5 and r.n == 2
    assert r.status == "regressed"                                          # 缺模型 ≤ 0 护栏


def test_skip_marker_gives_skipped(tmp_path):
    ctx = _ctx(tmp_path, gold=tmp_path)
    pred = R._skip(ctx, "缺模型 x")
    r = R.advset_score(ctx, pred)
    assert r.status == "skipped" and r.reason == "缺模型 x"


def test_sim_model_defaults_and_override(tmp_path):
    assert R._sim_model(_ctx(tmp_path, book="995ejelvk0")) == "models/glyph_sim_qtw/model.pt"
    assert R._sim_model(_ctx(tmp_path)) == ""
    assert R._sim_model(_ctx(tmp_path, book="995ejelvk0", args={"sim_model": "cov"})) == ""


def test_pairs_score(tmp_path):
    ctx = _ctx(tmp_path, guards=[])
    _jsonl(ctx.work / "pairs-rows.jsonl", [{"id": "a|b", "ok": True}, {"id": "a|c", "ok": False}])
    pred = tmp_path / "pairs.json"
    pred.write_text(json.dumps({"cov_high": 0.99, "n_pairs": 2, "n_pairs_excluded": 0,
                                "knn": {"precision": 0.99912, "recall": 0.1095, "fp": 3},
                                "random": {"fp": 0}, "best_operating_point": {"recall": 0.2055, "cov_high": 0.985}}),
                    encoding="utf-8")
    r = R.pairs_score(ctx, pred)
    assert r.metrics["knn 精度"] == 99.91 and r.metrics["knn 误放"] == 3 and r.metrics["random 误放"] == 0
    assert r.metrics["P≥0.999 最大召回"] == 20.55 and r.n == 2 and r.primary == "knn 精度"


def test_normalize_score(tmp_path):
    pred = tmp_path / "n.json"
    pred.write_text(json.dumps({"gate": {"n": 4, "passed": 3, "failed": [{"sample": "002"}], "ok": False},
                                "known_defect": {"n": 1, "changed": []},
                                "samples": [{"sample": "001", "passed": True, "status": "verified"},
                                            {"sample": "002", "passed": False, "status": "verified"},
                                            {"sample": "003", "status": "known_defect"}]}), encoding="utf-8")
    r = B.apply_guards(B.get("read-normalize"), R.normalize_score(_ctx(tmp_path, guards=[]), pred))
    assert r.metrics["回归门失败"] == 1 and r.metrics["回归门通过率"] == 75.0 and r.status == "ok"
    assert [x["ok"] for x in r.items] == [True, False, True]


def test_deprecated_legacy_ids_are_registered():
    for i in ("match_triplets", "match_pairs", "guard_ceiling", "db_match", "db_match_books", "rare_char", "zero_shot",
              "zero_shot_fusion", "oov", "degradation", "struct_rerank", "struct_heads"):
        s = B.get(i)
        assert s.deprecated and s.owner == "CV3"
