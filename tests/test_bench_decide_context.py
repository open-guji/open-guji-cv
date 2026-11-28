"""4b 文意三项 bench（eval/benches/decide_context.py）的打分口径，自造数据。"""
import json

from open_guji_cv.eval import bench as B
from open_guji_cv.eval.benches import decide_context as D


def _rr(cell, char, model="m", pv="candidates", cand=True):
    return {"kind": "ctx_ruling", "source": "llm", "cell": cell, "char": char, "model": model, "prompt_ver": pv, "in_candidates": cand}


def test_registered():
    for i in ("llm-context", "confusable-lm", "context-correction"):
        assert B.get(i).owner == "CV4"
    assert any(g.metric == "cache_miss_rate" for g in B.get("llm-context").guards)


def test_llm_context_scores_from_snapshot_and_counts_misses(tmp_path):
    f = tmp_path / "c.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in [_rr("a", "甲"), _rr("b", "丙"), _rr("c", "x", model="other"), _rr("z", "?", pv="direct")]) + "\n")
    items = [{"id": "a", "gold": "甲"}, {"id": "b", "gold": "乙"}, {"id": "c", "gold": "丁"}, {"id": "out", "gold": "戊"}]
    q = D.snapshot_cells(f)
    assert q == {"a", "b", "c", "z"}                         # 题集＝快照里出现过的格；evalset 里没有的 z、快照没有的 out 都不算
    m, rows = D.score_llm_context(items, D.load_rulings(f, "m", "candidates"), q)
    assert m["n"] == 3 and m["rescued"] == 1 and m["cache_miss"] == 1 and m["llm_accuracy"] == 0.3333   # c 没有 m 的裁定 → 缺，不算对
    assert [r["ok"] for r in rows] == [True, False, False]


def test_llm_context_run_is_deterministic_and_pins_sha(tmp_path, monkeypatch):
    ds = tmp_path / "ds" / "context-correction" / "llm-cache"
    ds.mkdir(parents=True)
    (ds / "2026-11-28.jsonl").write_text(json.dumps(_rr("a", "甲", model=D.DEFAULT_MODEL)) + "\n")
    ev = tmp_path / "evalset.json"
    ev.write_text(json.dumps({"items": [{"id": "a", "gold": "甲"}]}))
    monkeypatch.setattr(D, "EVALSET", ev)
    ctx = B.BenchCtx(book=D.BOOK, vols=[], work=tmp_path, res={"dataset": str(tmp_path / "ds")})
    r1 = D._score_llm(ctx, D._run_llm(ctx))
    r2 = D._score_llm(ctx, D._run_llm(ctx))
    assert r1.metrics == r2.metrics and r1.metrics["llm_accuracy"] == 1.0
    assert len(r1.env["llm_cache_sha256"]) == 64 and r1.env["llm_cache_sha256"] == r2.env["llm_cache_sha256"]


def test_llm_context_other_book_is_no_gold(tmp_path):
    ctx = B.BenchCtx(book="somebook", vols=[], work=tmp_path, res={})
    try:
        D._run_llm(ctx)
    except LookupError as e:
        assert str(e) == "no_gold"
    else:
        raise AssertionError


def test_confusable_and_cc_metrics():
    res = [{"id": "1", "pair": "p", "gold": "a", "tier": "hard_ref_silent", "pick": "a", "correct": True},
           {"id": "2", "pair": "p", "gold": "a", "tier": "hard_ref_silent", "pick": "b", "correct": False},
           {"id": "3", "pair": "p", "gold": "a", "tier": "easy_ref_gives_answer", "pick": "a", "correct": True}]
    m, items = D.score_confusable(res)
    assert m["acc_hard"] == 0.5 and m["acc_easy"] == 1.0 and m["n"] == 3 and len(items) == 3
    rep = {"rows": [{"book_weight": None, "top1_gain": 0.0}, {"book_weight": 0.9, "top1_gain": 0.05, "top1": 0.8, "baseline_top1": 0.75, "rescued": 6,
                                                         "harmed": 1, "harmful_flip_rate": 0.01, "glyph_layer_immutability": True, "n": 100}]}
    c = D.score_cc(rep)
    assert c["top1_gain"] == 0.05 and c["glyph_layer_immutable"] == 1 and c["harmed"] == 1


def test_corpus_args_from_res_and_arg_override(tmp_path):
    ctx = B.BenchCtx(book=D.BOOK, vols=[], work=tmp_path, res={"corpus": {"book_corpus": "/b.txt", "general_corpus": ["/g1", "/g2"]}})
    assert D._corpus_args(ctx) == ["--book-corpus", "/b.txt", "--general-corpus", "/g1", "--general-corpus", "/g2"]
    ctx.args = {"book_corpus": "/x"}
    assert D._corpus_args(ctx)[:2] == ["--book-corpus", "/x"] and "/b.txt" not in D._corpus_args(ctx)


def test_context_guard_registered_and_scored():
    spec = B.get("context-guard")
    assert spec.nogold and any(g.metric == "blocked_right" for g in spec.guards)
    res = {"base": {"rate": 0.01, "context": 5}, "v": {"blocked": 3, "wrong": 2, "right": 1, "unlabeled": 0, "missed": 1, "rate": 0.012,
                                                      "wrong_ids": ["a", "b"], "right_ids": ["c"], "missed_ids": ["d"]}}
    m, items = D.score_guard(res)
    assert m["blocked_right"] == 1 and m["review_rate_diff"] == 0.002 and len(items) == 4


def test_wave_report_reads_bench_result(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("wr", __import__("pathlib").Path(__file__).resolve().parents[1] / "scripts/zhengli/wave_report.py")
    wr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wr)
    d = tmp_path / "res"
    d.mkdir()
    (d / "result.json").write_text(json.dumps({"bench": "decide", "metrics": {"review_rate_body": 0.0145, "review_rate_diff": 0.0025,
                                                                              "new_wrong_cells": ["v:1:1:1"]}}), encoding="utf-8")
    v = wr.load_bench(str(d))["variants"]
    names = list(v)
    assert v[names[0]]["review_rate_body"] == 0.012 and v[names[1]]["new_wrong"] == ["v:1:1:1"] and v[names[1]]["fixed_wrong"] is None
    old = {"variants": {"A": {"review_rate_body": 0.01}}}
    p = tmp_path / "old.json"
    p.write_text(json.dumps(old))
    assert wr.load_bench(str(p)) == old               # 旧 eval_rough_bench json 原样
