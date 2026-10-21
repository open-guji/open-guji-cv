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


def test_zi_facts_keeps_claims_and_links_not_glosses():
    def node(k, prefix, form, zheng, gloss="同「X」，释义原文"):
        return [k, prefix, k, "0", form, form, form, gloss, None, None, zheng] + [None] * 6
    doc = {"yi": {"nodes": {
        "A": node("A", "GHZR", "互", ""),
        "B": node("B", "TVAR", "⿱一㐄", "互"),                 # 未编码形，正字 互
        "C": node("C", "GHZR", "牙", "互"),                    # 汉语大字典：牙 同 互
        "D": node("D", "GHZR", "㸦", ""),
        "E": node("E", "TVAR", "互", "手氏")},                  # 正字不是单字，不收
        "edges": [["A", "D"], ["A", "B"], ["A", "C"]]}}
    f = vs.zi_facts(doc)
    assert f["claims"] == [["TVAR", "B", "⿱一㐄", "互"], ["GHZR", "C", "牙", "互"]]
    assert f["links"] == [["A", "互", "C", "牙"], ["A", "互", "D", "㸦"]]   # 未编码那头不进连线
    assert "释义" not in json.dumps(f, ensure_ascii=False)


def test_zi_cache_upgrades_old_format(tmp_path):
    (tmp_path / f"U+{ord('蒙'):04X}.json").write_text(json.dumps({"q": "蒙", "fam": ["𫎇"]}), encoding="utf-8")
    calls = []

    def opener(req, timeout=0):
        calls.append(req.full_url)
        return _Resp(json.dumps(_zi_doc("蒙", ["𫎇"]), ensure_ascii=False).encode("utf-8"))

    z = vs.ZiCache(tmp_path, fetch=False, interval=0, opener=opener)
    assert z.ensure("蒙") is False and not calls             # 缺省不重取
    assert z.ensure("蒙", upgrade=True) is True and len(calls) == 1
    d = json.loads((tmp_path / f"U+{ord('蒙'):04X}.json").read_text(encoding="utf-8"))
    assert d["v"] == vs.ZI_CACHE_V and "claims" in d and "links" in d
    assert z.ensure("蒙", upgrade=True) is False and len(calls) == 1


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


def test_is_han_drops_compat_and_pua():
    assert vs.is_han("歷") and vs.is_han("𡚁")
    assert not vs.is_han("\uf98c")                       # 兼容区重复字 歷
    assert not vs.is_han("\ue000") and not vs.is_han("⺄") and not vs.is_han("ab")


def test_family_pool_merges_sources_and_tags(tmp_path):
    from open_guji_cv.hanzi import HanziDB
    edge = lambda a, b, src, d=0: (a, b, "variant", d, src, "", "", "")
    db = HanziDB.from_tables(tmp_path / "hz", {
        "sources": [], "forms": [],
        "edges": [edge("弊", "𡚁", "twedu", 1), edge("弊", "獘", "charcomp:rt"),
                  edge("弊", "敝", "hydzd-borrowed")],                     # 通假不进池
        "near": [("弊", "蔽", "near:v1", "slot", 0.95, "", 1)]})
    z = vs.ZiCache(tmp_path / "zi", fetch=False)
    (tmp_path / "zi").mkdir()
    (tmp_path / "zi" / f"U+{ord('弊'):04X}.json").write_text(
        json.dumps({"q": "弊", "fam": ["𡚁", "幣"]}, ensure_ascii=False), encoding="utf-8")
    pool = vs.family_pool(["弊"], zi=z, near_k=0, db=db)
    assert pool["弊"]["src"] == "piv"
    assert pool["𡚁"]["src"] == "v,zi"                  # 库里的异体表与本机字统网缓存都有
    assert pool["獘"]["src"] == "rt" and pool["幣"]["src"] == "zi"
    assert "敝" not in pool and "蔽" not in pool
    assert all(e["p"] == "弊" for e in pool.values())
    assert vs.family_pool(["弊"], near_k=1, db=db)["蔽"]["src"] == "near"


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


def test_alt_for_cards_cuts_patch_when_cache_missing(monkeypatch):
    """缓存里没有字块图（从产物包出单）时走 ctx 现切；没有 ctx 就跳过并记数。"""
    from open_guji_cv.clustering import rare_panel
    from open_guji_cv.review import alt_cands as ac

    class Bank:
        available = True
        def embed(self, img):
            return np.array([1.0, 0.0])
        def vectors(self, chars):
            return {c: np.array([1.0, 0.0]) if c == "已" else np.array([0.0, 1.0]) for c in chars}

    class Ctx:
        keys = []
        def image(self, kind, key):
            self.keys.append((kind, key))
            return np.zeros((8, 8), np.uint8)

    monkeypatch.setattr(rare_panel, "rare_patch", lambda *a, **k: None)
    monkeypatch.setattr(rare_panel, "_book_norm_stroke", lambda b: None)
    monkeypatch.setattr("open_guji_cv.clustering.normalize.normalize_patch", lambda img, stroke_width=None: img)
    monkeypatch.setattr(vs, "family_pool", lambda piv, zi=None: {"已": {"p": "己", "src": "v"}, "巳": {"p": "己", "src": "v"}})
    card = {"id": "b:3:1:6", "page": 3, "col": 1, "slot": 6, "char": "己"}
    logs = []
    assert ac.alt_for_cards("b", [card], bank=Bank(), log=logs.append) == {}
    assert any("取不到字块图" in m for m in logs)
    ctx = Ctx()
    got = ac.alt_for_cards("b", [card], bank=Bank(), ctx=ctx)
    assert [a["c"] for a in got["b:3:1:6"]] == ["已", "巳"] and ctx.keys == [("char_patch", "p0003c01s6")]


def test_family_pool_takes_symbols_only_when_a_pivot_is_one():
    """近似字里有特殊符号 → 整张符号表进池；纯汉字近似字不混进符号（设计 4.3）。"""
    from open_guji_cv.hanzi.symbols import is_symbol, symbols

    class Db:
        def pool(self, pivots, near_k=5, extra=None):
            return {p: {"p": p, "src": "piv"} for p in pivots if not is_symbol(p)}

    assert "○" in symbols() and not is_symbol("〇")
    got = vs.family_pool(["口", "○"], db=Db())
    assert got["○"] == {"p": "○", "src": "piv"} and got["◎"] == {"p": "○", "src": "sym"}
    assert set(symbols()) <= set(got) and got["口"]["src"] == "piv"
    assert not any(is_symbol(c) for c in vs.family_pool(["口", "日"], db=Db()))
