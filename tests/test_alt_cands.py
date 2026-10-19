# -*- coding: utf-8 -*-
"""审阅卡「相似字」alt：近似字 → 三家异体族合并 → 按字块图排序 → pending 字段。

数据全在测试里造（字统网响应、部件檢索表、向量），不联网、不需要 torch；
只有 `family_pool` 读本仓 `config/variants/variants.json` 的现成边（弊—𡚁）。
"""
from __future__ import annotations

import io
import json

import numpy as np

from open_guji_cv.clustering import variant_sources as vs
from open_guji_cv.review.alt_cands import attach, pivots_of, rank_pool
from open_guji_cv.review.proof_fields import pending_fields


def _zi_doc(q: str, forms: list[str]) -> dict:
    """仿字统网 /api/zi/<q>：一个字形＝q 的节点，连到若干节点（字形各为 forms 里的字）。"""
    def node(k, form, zheng=""):
        n = [k, "TVAR", k, "0", form, form, form, "", None, None, zheng]
        return n + [None] * 6
    nodes = {"Q": node("Q", q)}
    edges = []
    for i, f in enumerate(forms):
        nodes[f"N{i}"] = node(f"N{i}", f)
        edges.append(["Q", f"N{i}"])
    nodes["FAR"] = node("FAR", "遠")                  # 两跳外，不收
    edges.append(["N0", "FAR"])
    return {"yi": {"nodes": nodes, "edges": edges}}


def test_zi_parse_one_hop_encoded_only():
    doc = _zi_doc("弊", ["𡚁", "斃", "⿱敞大", ""])
    assert vs.zi_parse(doc, "弊") == sorted(["𡚁", "斃"])   # IDS 串、私用区不收，两跳外不收


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_zi_cache_fetch_writes_and_reverse_edge(tmp_path):
    calls = []

    def opener(req, timeout=0):
        calls.append(req.full_url)
        return _Resp(json.dumps(_zi_doc("蒙", ["𫎇"]), ensure_ascii=False).encode("utf-8"))

    z = vs.ZiCache(tmp_path, fetch=True, interval=0, opener=opener)
    assert z.family("蒙") == {"𫎇"}
    assert z.n_fetched == 1 and (tmp_path / f"U+{ord('蒙'):04X}.json").exists()
    # 只读模式、新实例：命中缓存不再取；反向边让 𫎇 也查得到 蒙
    z2 = vs.ZiCache(tmp_path, fetch=False, opener=opener)
    assert z2.family("蒙") == {"𫎇"}
    assert z2.family("𫎇") == {"蒙"}
    assert len(calls) == 1


def test_zi_cache_offline_failure_is_silent(tmp_path):
    def opener(req, timeout=0):
        raise OSError("断网")
    z = vs.ZiCache(tmp_path, fetch=True, interval=0, opener=opener)
    assert z.family("弊") == set()
    assert not list(tmp_path.glob("*.json"))          # 失败不写缓存，下次再试


def test_charcomp_and_compat_filter(tmp_path):
    f = tmp_path / "rt.tsv"
    f.write_text("# 头注\n歷\t厯歴歷\n", encoding="utf-8")
    assert vs.charcomp("歷", f) == {"厯", "歴"}         # 兼容区重复字、私用区都去掉


def test_family_pool_merges_sources_and_tags(tmp_path, monkeypatch):
    f = tmp_path / "rt.tsv"
    f.write_text("弊\t獘\n", encoding="utf-8")
    monkeypatch.setattr(vs, "CHARCOMP_TSV", f)
    z = vs.ZiCache(tmp_path / "zi", fetch=False)
    (tmp_path / "zi").mkdir()
    (tmp_path / "zi" / f"U+{ord('弊'):04X}.json").write_text(
        json.dumps({"q": "弊", "fam": ["𡚁", "幣"]}, ensure_ascii=False), encoding="utf-8")
    pool = vs.family_pool(["弊"], zi=z, near_k=0)
    assert pool["弊"]["src"] == "piv"
    assert "v" in pool["𡚁"]["src"] and "zi" in pool["𡚁"]["src"]   # 本仓表与字统网都有
    assert pool["獘"]["src"].endswith("rt") and pool["幣"]["src"] == "zi"
    assert all(e["p"] == "弊" for e in pool.values())


def test_pivots_of_priority_and_dedup():
    card = {"ref": {"char": "弊", "form": "獘"}, "ctx": {"char": "弊", "llm_suggestion": None},
            "db": {"candidates": [["敝", 0.9], ["幣", 0.8], ["蔽", 0.7], ["x", 0.1]]},
            "form": {"forms": ["𡚁"]}, "jys": None, "char": "敝"}
    assert pivots_of(card, ["斃"]) == ["弊", "獘", "敝", "幣", "蔽", "𡚁", "斃"]


def test_rank_pool_orders_by_cosine_and_drops_unrenderable():
    q = np.array([1.0, 0.0])
    vec = {"甲": np.array([0.6, 0.8]), "乙": np.array([1.0, 0.0]), "丙": np.array([0.0, 1.0])}
    pool = {c: {"p": "乙", "src": "v"} for c in ("甲", "乙", "丙", "丁")}       # 丁 渲染不出
    got = rank_pool(q, pool, lambda cs: {c: vec[c] for c in cs if c in vec}, k=2)
    assert [a["c"] for a in got] == ["乙", "甲"]
    assert got[0] == {"c": "乙", "s": 1.0, "p": "乙", "src": "v"}


def test_pending_fields_carries_alt():
    card = {"id": "b:1:2:3", "doubts": [], "ref": {"char": "弊", "op": "equal"}}
    attach([card], {"b:1:2:3": [{"c": "𡚁", "s": 0.912345, "p": "弊", "src": "v,zi"}]})
    out = pending_fields(card)
    assert out["alt"] == [{"c": "𡚁", "s": 0.9123, "p": "弊", "src": "v,zi"}]
    assert "alt" not in pending_fields({"id": "x", "doubts": []})


def test_alt_eval_ranks_and_hard_tier():
    from open_guji_cv.review.alt_cands import alt_eval
    cards = [
        {"id": "b:1", "ref": {"char": "弊"}, "alt": [{"c": "弊"}, {"c": "𡚁"}]},          # 整理本字即答案：不算难格
        {"id": "b:2", "ref": {"char": "弊"}, "db": {"candidates": [["敝", 0.9]]},
         "alt": [{"c": "斃"}, {"c": "獘"}, {"c": "𡚁"}]},                                 # 难格，排第 3
        {"id": "b:3", "ref": {"char": "歷"}, "alt": [{"c": "歷"}]},                      # 难格，没找到
        {"id": "b:4", "alt": [{"c": "甲"}]},                                             # 没人裁，不算
    ]
    res = alt_eval(cards, {"b:1": "弊", "b:2": "𡚁", "b:3": "厯"})
    assert res["all"]["n"] == 3 and res["all"]["top1"] == 1 and res["all"]["top3"] == 2
    assert res["hard"] == {"n": 2, "top1": 0, "top3": 1, "top5": 1, "top10": 1, "in_alt": 1, "mean_rank_when_hit": 3.0}
    assert res["hard_examples"][0] == {"g": "𡚁", "rank": 3, "old": "弊敝"}
