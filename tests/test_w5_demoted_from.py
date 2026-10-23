# -*- coding: utf-8 -*-
"""W5（GUJI-49）：后处理遍降级时在 `evidence.demoted_from` 记 `{"channel": 放行时通道, "by": 遍名}`。

9 处各一条（5 个后处理遍＋`_resolve_ji_yi_si` 2 处＋`_ji_yi_si_clf_cell` 2 处），自造数据。
另验：没放行过的格不加键；已有 evidence 键不丢；降级结果（admit／channel／char）与不加键时一致。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.steps.seed_admit as sa


def _rec(id_="r1", slot=1, char="山", channel="match_ref", admit=True, **kw):
    d = dict(id=id_, slot=slot, sub="", char=char, admit=admit, channel=channel, provenance="ref" if admit else "",
             doubts=[], evidence={"keep": 1})
    return NS(**{**d, **kw})


def _col(*recs, col=1):
    return NS(col=col, chars=list(recs))


def _df(rec):
    return (rec.evidence or {}).get("demoted_from")


def _assert_demoted(rec, by, channel="match_ref"):
    assert not rec.admit and rec.channel is None
    assert _df(rec) == {"channel": channel, "by": by}
    assert rec.evidence["keep"] == 1                      # 已有 evidence 键不丢


def test_demote_helper_only_when_admitted():
    a, b = _rec(), _rec(admit=False, channel=None)
    sa._demote(a, "x")
    sa._demote(b, "x")
    assert _df(a) == {"channel": "match_ref", "by": "x"} and a.admit and a.channel == "match_ref"
    assert _df(b) is None and b.evidence == {"keep": 1}


def test_shadow_veto(monkeypatch):
    v = NS(veto=True, pick=None, evidence=lambda *a: {"v": 1})
    gate = NS(judge=lambda ev: v, model="m", conf=0.9, low_conf=0.5)
    monkeypatch.setattr(sa, "_shadow_gate", lambda p: gate)
    monkeypatch.setattr(sa, "_doubts", lambda m, d: [])
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: None)
    r = _rec(channel="iron")
    m = NS(candidates=[("山", 1.0)], char="山")
    p = NS(shadow_veto_variant_abstain=False)
    assert sa._shadow_veto_pass(NS(), 1, p, [_col(r)], {r.id: m}, {}) == 1
    _assert_demoted(r, "shadow_veto", "iron")
    assert "shadow_veto" in r.evidence


def test_seal_blank_flip():
    r = _rec(channel="context")
    seal = {(1, 1, ""): {"seal_score": 0.9, "overlap": 0.8}}
    assert sa._seal_blank_flip([_col(r)], seal, {}) == 1
    _assert_demoted(r, "seal_blank_flip", "context")
    assert r.char is None
    r2 = _rec(admit=False, channel=None)                   # 本来就在待审：挪也不记 demoted_from
    sa._seal_blank_flip([_col(r2)], seal, {})
    assert _df(r2) is None


def _jys(monkeypatch):
    import open_guji_cv.utils.ji_yi_si as jys
    monkeypatch.setattr(jys, "resolve", lambda *a, **k: ("已", "默认"))


def _clf_p():
    return NS(ji_yi_si_clf_table="", ji_yi_si_clf_llm=False, ji_yi_si_clf_margin=0.0)


def test_diff_script(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("w5d", Path(__file__).parent.parent / "scripts" / "w5_demoted_diff.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def page(demoted):
        ev = {"keep": 1, **({"demoted_from": {"channel": "context", "by": "runt_cell_review"}} if demoted else {})}
        return {"columns": [{"col": 1, "chars": [{"id": "r1", "admit": False, "channel": None, "evidence": ev}]}]}

    for root, d in (("a", False), ("b", True)):
        p = tmp_path / root / "bk" / "seed_admit"
        p.mkdir(parents=True)
        (p / "p0001.json").write_text(json.dumps(page(d)), encoding="utf-8")
    r = m.compare(tmp_path / "a", tmp_path / "b", "bk")
    assert r["diff_pages"] == [] and r["bad"] == [] and r["demoted_from"] == {"runt_cell_review": 1}
    # 基线之外还有别的差异 → 报不同
    q = tmp_path / "b" / "bk" / "seed_admit" / "p0001.json"
    j = json.loads(q.read_text(encoding="utf-8"))
    j["columns"][0]["chars"][0]["evidence"]["keep"] = 2
    q.write_text(json.dumps(j), encoding="utf-8")
    assert m.compare(tmp_path / "a", tmp_path / "b", "bk")["diff_pages"] == ["p0001.json"]


def _sym_setup(monkeypatch, rare_top=None):
    import open_guji_cv.steps.align_ref as ar
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: None)
    monkeypatch.setattr(ar, "rare_topk_map", lambda r, k: {"r1": [rare_top]} if rare_top else {})
    return NS(symbol_min_human=3)


def test_symbol_review(monkeypatch):
    """特殊符号设计 S3：放行成符号的格退回待审，doubts 记 symbol；库里同符号人裁够数、走库匹配才放。"""
    p = _sym_setup(monkeypatch)
    r = _rec(char="○", channel="match_solo")
    assert sa._symbol_review_pass(NS(log=lambda s: None), 1, p, [_col(r)], {}, {}) == 1
    _assert_demoted(r, "symbol_review", "match_solo")
    assert "symbol" in r.doubts and r.evidence["symbol"] == "○"
    human = {f"b:1:1:{i}": "○" for i in range(3)}
    r2 = _rec(char="○", channel="match_solo")
    assert sa._symbol_review_pass(NS(log=lambda s: None), 1, p, [_col(r2)], {}, human) == 0
    assert r2.admit
    r3 = _rec(char="○", channel="context")             # 人裁够数也不让上下文放行符号
    assert sa._symbol_review_pass(NS(log=lambda s: None), 1, p, [_col(r3)], {}, human) == 1


def test_symbol_review_context_no_vote(monkeypatch):
    """库／5-b 首选是符号、上下文却放行成别的字 → 退回待审；纯汉字格不动。"""
    p = _sym_setup(monkeypatch, rare_top="●")
    r = _rec(char="口", channel="context")
    assert sa._symbol_review_pass(NS(log=lambda s: None), 1, p, [_col(r)], {}, {}) == 1
    assert r.evidence["symbol"] == "●"
    r2 = _rec(char="口", channel="match_ref")             # 库匹配放行的不动（库 top1 不是符号）
    assert sa._symbol_review_pass(NS(log=lambda s: None), 1, p, [_col(r2)], {"r1": NS(char="口")}, {}) == 0
    assert r2.admit and "symbol" not in r2.doubts
    p2 = _sym_setup(monkeypatch)
    r3 = _rec(char="山", channel="context")
    assert sa._symbol_review_pass(NS(log=lambda s: None), 1, p2, [_col(r3)], {"r1": NS(char="山")}, {}) == 0
    assert r3.evidence == {"keep": 1}


def test_symbol_review_params_hash_unchanged_when_off():
    d = sa.SeedAdmitParams().model_dump()
    assert "symbol_review" not in d and "symbol_min_human" not in d
    assert "symbol_review" in sa.SeedAdmitParams(symbol_review=True).model_dump()
