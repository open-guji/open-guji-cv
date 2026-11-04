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


def test_rare_panel_symbol_gate():
    """5-b 符号门槛（特殊符号设计 S3）：符号余弦 ≥ SYM_MIN 且高过本格最像的汉字才留，留下的排最前。"""
    from open_guji_cv.clustering.rare_panel import _sym_first, _symbol_gate
    assert _symbol_gate([("人", 0.988), ("亼", 0.978), ("△", 0.964)]) == frozenset()      # vol06 噪声
    assert _symbol_gate([("○", 0.964), ("◎", 0.942), ("口", 0.927), ("⊙", 0.914)]) == {"○", "◎"}
    assert _symbol_gate([("○", 0.92), ("口", 0.90)]) == frozenset()                        # 不到 SYM_MIN
    hits = [{"char": "口"}, {"char": "○"}, {"char": "乙"}, {"char": "◎"}]
    assert [h["char"] for h in _sym_first(hits, frozenset({"○", "◎"}))] == ["○", "◎", "口", "乙"]
    assert _sym_first(hits, frozenset()) is hits
