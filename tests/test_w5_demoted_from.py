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


def test_rare_cp_ctx_review():
    r = _rec(char="𠮓", channel="context")
    assert sa._rare_cp_ctx_pass([_col(r)], {}) == 1
    _assert_demoted(r, "rare_cp_ctx_review", "context")
    assert r.evidence["rare_cp_context"]["char"] == "𠮓"


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


def test_runt_cell_review(monkeypatch):
    cell = NS(slot=1, kind="char", raised=False, sub=None, flags=[], ink_ratio=0.2, y0=0.0, y1=40.0)
    cells = NS(columns=[NS(col=1, ok=True, period=100.0, n_body_slots=3, cells=[cell])])
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: cells)
    r = _rec(channel="context")
    p = NS(runt_min_ink=0.0, runt_ratio=0.6)
    assert sa._runt_cell_pass(NS(), 1, p, [_col(r)]) == 1
    _assert_demoted(r, "runt_cell_review", "context")


def test_rr_clf(monkeypatch):
    import open_guji_cv.utils.rr_clf as rc
    ch = sorted(rc.CLASSES)[0]
    other = sorted(rc.CLASSES)[1]
    monkeypatch.setattr(sa, "_page_patch", lambda *a, **k: object())
    monkeypatch.setattr(rc, "classify", lambda patch, model, p: {"pick": other})
    r = _rec(char=ch, channel="match_solo")
    p = NS(rr_clf_model="", rr_clf_p=0.5, patch_missing="raise")
    assert sa._rr_clf_pass(NS(), 1, p, [_col(r)], {}) == 1
    _assert_demoted(r, "rr_clf", "match_solo")


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


def test_ji_yi_si_ctx_review(monkeypatch):
    import open_guji_cv.utils.near_form_ctx as nf
    _jys(monkeypatch)
    monkeypatch.setattr(nf, "decide", lambda *a, **k: (None, "x"))
    r = _rec(char="已", channel="context")
    sa._resolve_ji_yi_si([_col(r)], {}, {}, {}, False, ctx_rule=(0.98, 5))
    _assert_demoted(r, "ji_yi_si_ctx_review", "context")


def test_ji_yi_si_review(monkeypatch):
    _jys(monkeypatch)
    r = _rec(char="已", channel="context")
    sa._resolve_ji_yi_si([_col(r)], {}, {}, {}, True)
    _assert_demoted(r, "ji_yi_si_review", "context")


def _clf_p():
    return NS(ji_yi_si_clf_table="", ji_yi_si_clf_llm=False, ji_yi_si_clf_margin=0.0)


def test_ji_yi_si_clf_conflict(monkeypatch):
    import open_guji_cv.utils.ji_yi_si_clf as c
    monkeypatch.setattr(c, "classify", lambda l, r: ("己", "x"))
    r = _rec(char="已", channel="match_ref")
    assert sa._ji_yi_si_clf_cell(r, [r], 0, {}, _clf_p()) == (-1, 1)
    _assert_demoted(r, "ji_yi_si_clf_conflict", "match_ref")


def test_ji_yi_si_clf_review(monkeypatch):
    import open_guji_cv.utils.ji_yi_si_clf as c
    monkeypatch.setattr(c, "classify", lambda l, r: (None, "x"))
    r = _rec(char="已", channel="split_ref")
    assert sa._ji_yi_si_clf_cell(r, [r], 0, {}, _clf_p()) == (-1, 1)
    _assert_demoted(r, "ji_yi_si_clf_review", "split_ref")


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
