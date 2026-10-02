# -*- coding: utf-8 -*-
"""规则 A 放行通道 `rare_ref`（2026-10-02，D3 道 overview#349）与影子升级 `shadow_promote`。全部自造数据。

规则 A：整理本 replace 段、5-b 首位**逐字**等于整理本字 → 放行整理本字；一串硬护栏照拦；缺省关、关着产物逐字节不变。
影子升级：待审格上影子首选 == 整理本字或库首位且把握度够 → 放行；缺省关。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_align_ref, page_decision, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.spec import live_optional_consumes
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import ColumnRare, PageRare, RareCand, RareRec
from open_guji_cv.shadow import signals as S
from open_guji_cv.shadow.gate import ShadowGate, decide_promote, promote_judge
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams, SeedAdmitStep, rare_ref_decide

BOOK, PAGE, COL = "tbook", 1, 1
REF, LIB = "盡", "畫"          # 实例取自 vol02:168:3:21：整理本「盡」、库首位「畫」、5-b 首位「盡」


def _rare(cands: dict[int, list[str]]) -> PageRare:
    recs = [RareRec(id=f"{BOOK}:{PAGE}:{COL}:{s}", slot=s,
                    candidates=[RareCand(char=c, score=0.9 - 0.01 * i, font="emb") for i, c in enumerate(cs)])
            for s, cs in cands.items()]
    return PageRare(page=PAGE, columns=[ColumnRare(col=COL, ok=True, chars=recs)])


def _run(tmp_path, monkeypatch, *, rare, cands=((LIB, 0.95),), verdict="unsure", guard=None, char=None,
         align=(REF, "replace"), params=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict=verdict, char=char, cov=cands[0][1], wmax=16.0,
                                         guard=guard, candidates=list(cands))]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.1, source="prior")]))
    if align:
        write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
            PAGE, BOOK, col=COL, recs=[dict(slot=1, align_char=align[0], align_op=align[1])]))
    if rare is not None:
        write_product(ctx, "rare_candidates", PAGE, rare_candidates=_rare({1: rare}))
    ctx.params["seed_admit"] = SeedAdmitParams(**(params or {}))
    (col,) = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"].columns
    (r,) = col.chars
    return r


ON = {"rare_ref": True}


# ── 声明与指纹 ───────────────────────────────────────────────────────────
def test_declared_as_gated_optional_upstream():
    spec = STEPS["seed_admit"].spec
    for field in ("rare_ref", "shadow_promote"):
        assert ("rare_candidates", field) in spec.optional_consumes_when
        on = spec.params().model_copy(update={field: True})
        assert "rare_candidates" in live_optional_consumes(spec, on)
    assert "rare_candidates" not in live_optional_consumes(spec, spec.params())


def test_params_off_is_invisible(tmp_path):
    """关着时新增字段一个都不进 dump → params_hash 与加字段前逐位相同；开着时进。"""
    db = str(tmp_path / "g.db")
    off = SeedAdmitParams(db_path=db)
    assert not any(k.startswith(("rare_ref", "shadow_promote")) for k in off.model_dump())
    assert SeedAdmitParams(db_path=db, rare_ref=False).model_dump() == off.model_dump()
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    h = lambda p: params_hash(p, sp, pt)  # noqa: E731
    on = SeedAdmitParams(db_path=db, rare_ref=True)
    assert on.model_dump()["rare_ref"] is True and h(on) != h(off)
    # 只开 rare_ref 不拖进影子模型字段（没有模型文件也能建参数）
    assert not any(k.startswith("shadow") for k in on.model_dump())


# ── 规则 A 通道 ──────────────────────────────────────────────────────────
def test_off_leaves_cell_in_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, rare=[REF, LIB])
    assert not r.admit and "replace_align" in r.doubts and "rare_ref" not in r.evidence


def test_off_product_unchanged_when_rare_missing_or_present(tmp_path, monkeypatch):
    """关着时 5-b 在不在都一个样（不读它）。"""
    a = _run(tmp_path, monkeypatch, rare=[REF, LIB])
    b = _run(tmp_path, monkeypatch, rare=None)
    assert a.model_dump() == b.model_dump()


def test_on_admits_ref_char_with_evidence(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, rare=[REF, LIB], params=ON)
    assert r.admit and r.channel == "rare_ref" and r.provenance == "rare_ref" and r.char == REF
    assert r.doubts == []
    assert r.evidence["rare_ref"] == {"rare": REF, "ref": REF, "lib": LIB, "cov": 0.95}


@pytest.mark.parametrize("kw", [
    dict(rare=[LIB, REF]),                                   # 5-b 首位不是整理本字
    dict(rare=[REF], align=(REF, "equal")),                  # 不是 replace 段
    dict(rare=["己"], align=("己", "replace")),              # 己已巳
    dict(rare=[REF], guard="never_match"),                   # 库护栏
    dict(rare=[REF], guard="conflict"),
    dict(rare=[REF], verdict="same", char=LIB, cands=((LIB, 0.999),)),   # 库明确认成别的字
    dict(rare=["裏"], align=("裏", "replace"), cands=(("裡", 0.95),)),   # 库首位是整理本字的异体
    dict(rare=None),                                         # 没有 5-b 产物
])
def test_blocked_cases_stay_in_review(tmp_path, monkeypatch, kw):
    r = _run(tmp_path, monkeypatch, params=ON, **kw)
    assert r.channel != "rare_ref" and "rare_ref" not in r.evidence     # 己已巳走 split_ref，不归本通道
    if kw.get("rare") != ["己"]:
        assert not r.admit and r.channel is None


def test_already_admitted_cell_not_touched(tmp_path, monkeypatch):
    """库 same 且与整理本一致 → 现行通道放行；规则 A 不改它的通道与字。"""
    kw = dict(rare=[REF], verdict="same", char=REF, cands=((REF, 0.999),), align=(REF, "equal"))
    base = _run(tmp_path, monkeypatch, **kw)
    on = _run(tmp_path, monkeypatch, params=ON, **kw)
    assert base.admit and on.model_dump() == base.model_dump()


def test_hard_doubts_pure():
    ok = dict(doubts=[], guard=None, verdict="unsure", lib_char=None, lib_top=LIB, ref=REF, op="replace",
              rare_top=REF, are_variants=lambda a, b: False)
    assert rare_ref_decide(**ok) == REF
    for d in ("occluded", "excluded", "near_form", "context_blank_cell", "form_open", "approx_exemplar", "护栏:conflict"):
        assert rare_ref_decide(**{**ok, "doubts": ["replace_align", d]}) is None, d
    assert rare_ref_decide(**{**ok, "doubts": ["replace_align", "库 unsure(cov=0.950)"]}) == REF
    assert rare_ref_decide(**{**ok, "lib_top": REF}) == REF          # 库首位就是整理本字：不算「别字」


# ── 影子升级 ─────────────────────────────────────────────────────────────
class _Stub:
    def __init__(self, table):
        self.table, self.version = table, "stub@0"
        self.meta = {"signal_version": S.SIGNAL_VERSION, "model_id": "stub"}

    def scores(self, rows):
        return [self.table.get(r["cand"], 0.01) for r in rows]


class _VM:
    def semantic(self, c):
        return c


def _gate(table):
    return ShadowGate(_Stub(table), S.SignalContext(vm=_VM(), partners={}, human_ids={}, lib_ids=frozenset()), 0.9)


def test_decide_promote_needs_backing_and_confidence():
    ev = S.CellEvidence("v:1:1:1", lib=[(LIB, .9), ("盡", .5)], rare=[("盡", .9)], ref=REF, cur=None)
    assert decide_promote(REF, .95, ev, .9).promote and decide_promote(REF, .95, ev, .9).backed_by == ("ref",)
    assert decide_promote(LIB, .95, ev, .9).backed_by == ("lib",)
    assert decide_promote(REF, .5, ev, .9).reason == "below_thr"
    assert decide_promote("書", .99, ev, .9).reason == "no_backing"        # 影子自己提名的字不放
    assert decide_promote("己", .99, S.CellEvidence("v:1:1:1", ref="已"), .9).reason == "jys"


def test_promote_judge_abstains():
    ev = S.CellEvidence("v:1:1:1", lib=[(LIB, .9)], ref=REF)
    g = _gate({REF: .95})
    assert promote_judge(g, ev, .9).promote
    g.ctx.lib_ids = frozenset({"v:1:1:1"})
    assert promote_judge(g, ev, .9).reason == "abstain:self_in_lib"
    assert promote_judge(g, ev, .9, check_self=False).promote           # 离线评测口径

    class Boom(_Stub):
        def scores(self, rows):
            raise ValueError("x")
    assert promote_judge(ShadowGate(Boom({}), g.ctx, .9), ev, .9, check_self=False).reason.startswith("abstain:error")


def test_v2_features_and_v1_candidate_set():
    ev = S.CellEvidence("v:1:1:1", lib=[("裡", .9)], rare=[("盡", .9), ("裏", .5)], ref="裏", cur="裡")
    rows = {r["cand"]: r for r in S.build_rows(ev, _VCtx())}
    assert rows["盡"]["rare_rank"] == 0 and rows["盡"]["rare_top1"] == 1 and rows["裏"]["rare_rank"] == 1
    assert rows["裏"]["ref_rare1"] == 0 and rows["裏"]["lib_ref_var"] == 1      # 库首位裡 是 裏 的异体
    v1 = {r["cand"] for r in S.build_rows(ev, _VCtx(), "1")}
    # v1 候选集 = 库 top5 ∪ 5b 按 score 前 3 ∪ 整理本 ∪ 现字；名次首位「盡」本来也在 score 前 3 里，用更窄的例子测差别
    ev2 = S.CellEvidence("v:1:1:2", lib=[("裡", .9)], rare=[("甲", .1), ("乙", .9), ("丙", .8), ("丁", .7)], cur="裡")
    assert "甲" not in {r["cand"] for r in S.build_rows(ev2, _VCtx(), "1")}
    assert "甲" in {r["cand"] for r in S.build_rows(ev2, _VCtx(), "2")}
    assert v1 >= {"裡", "盡", "裏"}


def _VCtx():
    return S.SignalContext(vm=_VM(), partners={}, human_ids={}, lib_ids=frozenset())


def test_seed_admit_promote_only_promotes(tmp_path, monkeypatch):
    """端到端：关 = 与不带参数逐字一致；开 = 待审格被放行、evidence 留痕；无背书／把握度不够不动。"""
    base = _run(tmp_path, monkeypatch, rare=[REF, LIB])
    assert not base.admit
    off = _run(tmp_path, monkeypatch, rare=[REF, LIB], params={"shadow_promote": False})
    assert off.model_dump() == base.model_dump()

    monkeypatch.setattr(sa, "_shadow_gate", lambda _p: _gate({REF: .95, LIB: .02}))
    prm = {"shadow_promote": True, "shadow_promote_conf": 0.9, "shadow_model_fingerprint": "x"}
    on = _run(tmp_path, monkeypatch, rare=[REF, LIB], params=prm)
    assert on.admit and on.channel == "shadow" and on.provenance == "shadow" and on.char == REF
    ev = on.evidence["shadow_promote"]
    assert ev["pick"] == REF and ev["backed_by"] == ["ref"] and ev["conf"] >= 0.9 and "replace_align" in ev["prev_doubts"]
    # 把握度不够 → 不动
    monkeypatch.setattr(sa, "_shadow_gate", lambda _p: _gate({REF: .5, LIB: .45}))
    assert not _run(tmp_path, monkeypatch, rare=[REF, LIB], params=prm).admit
    # 影子选了无背书的字 → 不动
    monkeypatch.setattr(sa, "_shadow_gate", lambda _p: _gate({"書": .95}))
    assert not _run(tmp_path, monkeypatch, rare=[REF, LIB, "書"], params=prm).admit
    # 硬护栏（库护栏）→ 不动
    monkeypatch.setattr(sa, "_shadow_gate", lambda _p: _gate({REF: .95}))
    assert not _run(tmp_path, monkeypatch, rare=[REF], guard="never_match", params=prm).admit
