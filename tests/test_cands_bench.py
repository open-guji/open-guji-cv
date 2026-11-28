"""候选字线两个 bench（eval/benches/cands.py）的打分口径：自造 per 行，不用 torch、不读测试集。"""
from __future__ import annotations

import json
from pathlib import Path

from open_guji_cv.eval import bench as B
from open_guji_cv.eval.benches import cands as C


def _x(i, layer="A", r_cand=1, r_full=1, r_rare=None, r_chain=None, r_img=None, **kw):
    d = {"id": f"{layer}:{i}", "layer": layer, "st": kw.pop("st", {}), "r_cand": r_cand, "r_full": r_full, "r_rare": r_rare}
    if r_chain is not None:
        d.update(r_chain=r_chain, r_chain_img=r_img, fixed_n=0)
    d.update(kw)
    return d


def _pred(tmp_path: Path, per: list[dict]) -> tuple[Path, B.BenchCtx]:
    p = tmp_path / "pred"
    p.mkdir()
    (p / "per.json").write_text(json.dumps(per), encoding="utf-8")
    (p / "meta.json").write_text(json.dumps({"n_rows": len(per), "nonchar": {"B:seg": 2}, "emb": "emb-x", "lm": "lm@y", "w": 0.005}),
                                 encoding="utf-8")
    return p, B.BenchCtx("988g3f0wsu", [], tmp_path, {})


def test_registered_with_ids_and_books():
    for bid in ("read-3c-cands", "decide-4b-ctx"):
        s = B.get(bid)
        assert s.owner == "CV3" and s.needs == ("gold", "torch")
        assert s.gold_rel("siku-zongmu") == "char-candidates" and s.gold_rel("99k3i35yww") is None
    assert C.ITEM_BOOK["siku-zongmu"] == "96mid1ogzk"      # 框架用工作区 id，测试集记的是书 id


def test_3c_recall_by_layer_and_items(tmp_path):
    per = [_x(1, r_cand=1), _x(2, r_cand=10), _x(3, r_cand=11), _x(4, r_cand=None),
           _x(5, layer="B", r_cand=3, r_rare=1)]
    pred, ctx = _pred(tmp_path, per)
    r = C.score_3c(ctx, pred)
    m = r.metrics
    assert (m["n_A"], m["n_B"]) == (4, 1)
    assert (m["recall_at_1"], m["recall_at_10"], m["recall_at_30"], m["recall_at_50"]) == (25.0, 50.0, 75.0, 75.0)
    assert m["b_recall_at_1"] == 0.0 and m["b_recall_at_10"] == 100.0 and m["b_frozen_3b_at_10"] == 100.0
    assert r.primary == "recall_at_10" and r.n == 5 and m["nonchar"] == {"B:seg": 2}
    ok = {x["id"]: x["ok"] for x in r.items}
    assert ok == {"A:1": True, "A:2": True, "A:3": False, "A:4": False, "B:5": True}   # ok＝进前 10


def test_4b_gain_harm_and_flips(tmp_path):
    # 图像首位对的 3 格里重排挤掉 1 格＝伤害率 33.33；另 1 格图像首位错、重排后对＝增益
    per = [_x(1, r_chain=1, r_img=1), _x(2, r_chain=1, r_img=1), _x(3, r_chain=2, r_img=1),
           _x(4, r_chain=1, r_img=3), _x(5, r_chain=None)]
    pred, ctx = _pred(tmp_path, per)
    r = C.score_4b(ctx, pred)
    m = r.metrics
    assert m["n_ctx"] == 4 and m["chain_top1"] == 75.0 and m["img_top1"] == 75.0 and m["gain_top1"] == 0.0
    assert m["harm_rate"] == 33.33 and r.primary == "chain_top1"
    assert [x["id"] for x in r.items] == ["A:1", "A:2", "A:3", "A:4"]       # 没前后文的格不进
    # 护栏：伤害率 33.33 越线 → regressed；增益 0 不算越线（min 0）
    s = B.get("decide-4b-ctx")
    B.apply_guards(s, r)
    st = {g["metric"]: g["status"] for g in r.guards}
    assert st["harm_rate"] == "regressed" and st["gain_top1"] == "ok" and r.status == "regressed"


def test_4b_without_context_rows_does_not_crash(tmp_path):
    pred, ctx = _pred(tmp_path, [_x(1)])
    r = C.score_4b(ctx, pred)
    assert r.metrics["n_ctx"] == 0 and r.metrics["chain_top1"] is None and r.items == []
