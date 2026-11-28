"""benchmark 统一接口（eval/bench.py）：登记、金标定位、护栏、翻转清单、结果落盘。自造数据。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.eval import bench as B


def _spec(**kw):
    def run(ctx):
        return ctx.work

    def score(ctx, pred):
        items = json.loads((pred / "items.json").read_text(encoding="utf-8"))
        acc = sum(x["ok"] for x in items) / len(items)
        return B.BenchResult("t", ctx.book, ctx.vols, {"acc": acc, "bad": len(items) - sum(x["ok"] for x in items)},
                             "acc", items=items)
    d = dict(id="t", title="t", steps=("s",), owner="CV0", gold="x/y", needs=("gold",), primary="acc",
             run=run, score=score)
    d.update(kw)
    return B.BenchSpec(**d)


def _ctx(tmp_path, items):
    w = tmp_path / "w"
    w.mkdir(exist_ok=True)
    (w / "items.json").write_text(json.dumps(items), encoding="utf-8")
    return B.BenchCtx("bk", ["01"], w, {}, env={"cv": "x"})


def test_spec_validates_needs_and_mode():
    with pytest.raises(ValueError):
        _spec(needs=("gold", "nope"))
    with pytest.raises(ValueError):
        _spec(mode="other")


def test_gold_rel_forms():
    assert _spec(gold="cut/").gold_rel("bk") == "cut/bk"
    s = _spec(gold={"bk": "a/b", "bv": {"01": "c/01", "02": "c/02"}})
    assert s.gold_rel("bk") == "a/b" and s.gold_rel("bv", "02") == "c/02" and s.gold_rel("bv") == "c/01"
    assert s.gold_rel("zz") is None and s.gold_books() == ["bk", "bv"]
    assert _spec().gold_books() is None


def test_guards_and_status(tmp_path):
    s = _spec(guards=(B.Guard("bad", "max", 0), B.Guard("missing", "max", 0)))
    r = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": True}, {"id": 2, "ok": False}]))
    assert r.status == "regressed" and r.n == 2
    st = {g["metric"]: g["status"] for g in r.guards}
    assert st == {"bad": "regressed", "missing": "unverified"}
    r = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": True}]))
    assert r.status == "ok"


def test_against_flips_and_self_zero(tmp_path):
    s = _spec(guards=(B.Guard("flip_worse", "max", 0),))
    before = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": True}, {"id": 2, "ok": False}, {"id": 3, "ok": True}]))
    out = B.write_result(tmp_path / "r0", before)
    assert json.loads((out / "result.json").read_text(encoding="utf-8"))["schema"] == B.SCHEMA
    same = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": True}, {"id": 2, "ok": False}, {"id": 3, "ok": True}]), against=out)
    assert same.against["worse"] == same.against["better"] == 0 and same.status == "ok"
    now = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": False}, {"id": 2, "ok": True}, {"id": 3, "ok": True}]), against=out)
    assert now.metrics["flip_worse"] == 1 and now.metrics["flip_better"] == 1 and now.status == "regressed"
    rep = (B.write_result(tmp_path / "r1", now) / "report.md").read_text(encoding="utf-8")
    assert "变坏 1" in rep


def test_registry_has_samples_and_suites():
    ids = [s.id for s in B.all_specs()]
    assert {"cut-2d", "decide"} <= set(ids)
    assert "cut-2d" in [s.id for s in B.expand(["@cut"])]
    with pytest.raises(KeyError):
        B.get("nope")
    with pytest.raises(KeyError):
        B.expand(["@nope"])
    for s in B.all_specs():
        assert s.owner and (s.deprecated or (s.primary and s.steps))     # deprecated 的只留理由，不跑


def test_decide_score(tmp_path):
    from open_guji_cv.eval.benches import decide
    p = tmp_path / "a.jsonl"
    rows = [{"id": "a", "outcome": "放对"}, {"id": "b", "outcome": "放错字"}, {"id": "c", "outcome": "拦住·首选对"},
            {"id": "d", "outcome": "拦住·首选错"}]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    (tmp_path / "decide-bench" / "small").mkdir(parents=True)
    (tmp_path / "decide-bench" / "small" / "bench.yaml").write_text("books:\n- {ws: bk, vol: '01'}\n", encoding="utf-8")
    ctx = B.BenchCtx("bk", [], tmp_path, {"dataset": str(tmp_path)})
    r = decide.score(ctx, p)
    assert r.metrics["wrong_admit"] == 1 and r.metrics["admit_rate"] == 0.5 and r.metrics["review_top1_ok"] == 0.5
    assert r.metrics["missing_rate"] == 0.0
    assert [x["ok"] for x in r.items] == [True, False, True, False] and r.vols == ["01"]
    r = B.apply_guards(B.get("decide"), r)
    assert r.status == "regressed"


def test_flip_guard_na_without_against_and_cmp_skip(tmp_path):
    s = _spec(guards=(B.Guard("flip_worse", "max", 0), B.Guard("nope", "max", 0)))
    r = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": True}]))
    st = {g["metric"]: g["status"] for g in r.guards}
    assert st == {"flip_worse": "n/a", "nope": "unverified"}
    out = B.write_result(tmp_path / "r0", r)
    now = B.execute(s, _ctx(tmp_path, [{"id": 1, "ok": False, "cmp_skip": True}]), against=out)
    assert now.against["worse"] == 0


def test_needs_accepts_bench5b():
    from open_guji_cv.eval import bench as B
    B.BenchSpec(id="t-5b", title="t", steps=("glyph_match",), owner="CV3", gold="x", needs=("bench5b",),
                primary="acc", run=lambda c: c.work, score=lambda c, p: None)
