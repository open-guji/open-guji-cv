"""按上下文排序 `context_rank`（2026-11-27）：融合、池、邻格字、整页读序与前后文、缺模型不炸、缺省关、骨架位置。全部自造数据，假填空模型。"""
from __future__ import annotations

from types import SimpleNamespace

from open_guji_cv.clustering import ctx_fill
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.products.kinds.read import FinalCand, FinalRec
from open_guji_cv.steps import context_rank as cr

from helpers import page_decision, page_match


def test_fuse_sem_breaks_tie_but_not_a_big_image_gap():
    pool = [("甲", 0.90), ("乙", 0.89), ("丙", 0.60)]
    sem = {"甲": -9.0, "乙": -2.0, "丙": -1.0}
    got = ctx_fill.fuse(pool, sem, 0.005)
    assert [c for c, _, _ in got][:2] == ["乙", "甲"]          # 图像差 0.01，填空差 7 分×0.005＝0.035 → 换
    assert got[-1][0] == "丙"                                   # 图像差 0.3，填空补不回来


def test_fuse_missing_char_gets_median_and_floor():
    pool = [("甲", 0.5), ("乙", 0.5), ("丙", 0.5)]
    got = dict((c, f) for c, f, _ in ctx_fill.fuse(pool, {"甲": -3.0, "乙": -20.0}, 0.01))
    assert abs(got["乙"] - (0.5 + 0.01 * ctx_fill.FLOOR)) < 1e-9     # 下限 −12
    assert got["丙"] == 0.5 + 0.01 * -3.0 or got["丙"] > got["乙"]   # 缺字取中位数，不垫底


def test_pool_prefers_analyzer_cands_with_best_image_sim():
    m = page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": [("甲", 0.9)]}]).columns[0].chars[0]
    fin = FinalRec(id=m.id, slot=1, cands=[
        FinalCand(char="甲", evidence={"a": {"sim": 0.9}, "c": {"sim": 0.95}}),
        FinalCand(char="乙", evidence={"c": {"sim": 0.7}}),
        FinalCand(char="丙", evidence={"b": {"x": 1}})])          # 没有图像分的不进池
    assert cr.pool_of(m, fin) == [("甲", 0.95), ("乙", 0.7)]
    assert cr.pool_of(m, None) == [("甲", 0.9)]


def test_best_char_priority():
    m = page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": [("乙", 0.5)]},
                         {"slot": 2, "verdict": "diff"}]).columns[0].chars
    d = page_decision(recs=[{"slot": 1, "char": "甲", "source": "context", "ranked": [("丙", 1.0)]}]).columns[0].chars[0]
    assert cr.best_char(m[0], d) == "甲"
    d2 = page_decision(recs=[{"slot": 1, "char": None, "source": "prior", "ranked": [("丙", 1.0)]}]).columns[0].chars[0]
    assert cr.best_char(m[0], d2) == "丙"
    assert cr.best_char(m[0], None) == "乙"
    assert cr.best_char(m[1], None) == ctx_fill.MISSING


class _FakeLM:
    def __init__(self, table):
        self.table, self.seen = table, []

    def sem(self, left, right, chars):
        self.seen.append((left, right))
        return {c: self.table.get(c, -10.0) for c in chars}


def _ctx(match, dec=None, fin=None, **kw):
    prods = {"glyph_match": match, "context_decision": dec, "glyph_analyzer": fin}
    p = cr.ContextRankParams(enabled=True, **kw)

    def product(kind, page):
        v = prods.get(kind)
        if v is None:
            raise KeyError(kind)
        return v
    return SimpleNamespace(params_for=lambda _s: p, product=product)


def test_run_page_context_is_reading_order_and_excludes_self(monkeypatch):
    lm = _FakeLM({"乙": -1.0, "甲": -8.0})
    monkeypatch.setattr(ctx_fill, "shared", lambda: lm)
    m = page_match(recs=[
        {"slot": 1, "verdict": "same", "char": "天"},
        {"slot": 2, "verdict": "unsure", "candidates": [("甲", 0.80), ("乙", 0.79)]},
        {"slot": 3, "verdict": "unsure", "candidates": [("地", 0.5)]},
    ])
    out = cr.ContextRankStep().run_page(_ctx(m), 1)["context_rank"]
    recs = {r.slot: r for c in out.columns for r in c.chars}
    assert recs[1].ran is False and recs[1].why == "same"
    assert recs[3].ran is False and recs[3].why == "pool<2"
    assert recs[2].ran and [r[0] for r in recs[2].ranked] == ["乙", "甲"]      # 填空把 乙 抬到前面
    assert lm.seen == [("天", "地")]                                           # 左＝前一格，右＝后一格，本格不在里面
    assert recs[2].ranked[0][2] == 0.79 and recs[2].ranked[0][3] == -1.0       # 图像分、logp 都记下


def test_run_page_without_lm_marks_no_lm(monkeypatch):
    monkeypatch.setattr(ctx_fill, "shared", lambda: None)
    m = page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": [("甲", 0.8), ("乙", 0.7)]}])
    out = cr.ContextRankStep().run_page(_ctx(m), 1)["context_rank"]
    r = out.columns[0].chars[0]
    assert r.ran is False and r.why == "no_lm" and r.ranked == []


def test_default_off_and_in_decide_stage_before_seed_admit():
    assert cr.ContextRankParams().enabled is False
    d = load_pipeline("keben_body_v2").stages["decide"]
    assert d.index("context_decide") < d.index("context_rank") < d.index("char_decide")


def test_neighbor_texts_reading_order_and_decision_overrides():
    m = page_match(recs=[{"slot": 1, "verdict": "same", "char": "天"},
                         {"slot": 2, "verdict": "unsure", "candidates": [("甲", 0.8), ("乙", 0.7)]},
                         {"slot": 3, "verdict": "same", "char": "地"}])
    d = page_decision(recs=[{"slot": 2, "char": "丙", "source": "context"}])
    nt = cr.neighbor_texts(m, d)
    assert nt["tbook:1:1:2"] == ("天", "地") and nt["tbook:1:1:1"] == ("", "丙地")
    assert cr.neighbor_texts(m)["tbook:1:1:1"] == ("", "甲地")      # 没有 context_decision：取 3a 第一候选
