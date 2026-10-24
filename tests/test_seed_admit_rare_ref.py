# -*- coding: utf-8 -*-
"""规则 A 放行通道 `rare_ref`（2026-10-02，D3 道 overview#349）。全部自造数据（影子升级 `shadow_promote` 开关已随 W2 删，`shadow/gate.py` 的 `decide_promote`／`promote_judge` 留作离线评测口径，下面两条单测仍测它们）。

规则 A：整理本 replace 段、5-b 首位**逐字**等于整理本字 → 放行整理本字；一串硬护栏照拦；缺省关、关着产物逐字节不变。
影子升级（`shadow_promote`）已随 W2 删除；下面只留 `shadow/gate.py` 离线评测口径的单测。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_align_ref, page_decision, page_match, write_product
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.spec import live_optional_consumes
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import ColumnRare, CoordRec, PageRare, RareCand, RareRec
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
         align=(REF, "replace"), params=None, coord=None):
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, verdict=verdict, char=char, cov=cands[0][1], wmax=16.0,
                                         guard=guard, candidates=list(cands))]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL, recs=[dict(slot=1, char=None, margin=0.1, source="prior")]))
    if align or coord is not None:
        # coord：只给坐标对位、现役对位里缺这一格（另摆一个对得上的格，页才算锚上）
        recs = ([dict(slot=1, align_char=align[0], align_op=align[1])] if align
                else [dict(slot=2, align_char="之", align_op="equal")])
        ar = page_align_ref(PAGE, BOOK, col=COL, recs=recs)
        if coord is not None:
            ar.coord = [CoordRec(id=f"{BOOK}:{PAGE}:{COL}:1", col=COL, slot=1, ref_char=coord)]
        write_product(ctx, "align_ref", PAGE, align_ref=ar)
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
    for field in ("rare_ref",):
        assert ("rare_candidates", field) in spec.optional_consumes_when
        on = spec.params().model_copy(update={field: True})
        assert "rare_candidates" in live_optional_consumes(spec, on)
    assert "rare_candidates" not in live_optional_consumes(spec, spec.params())


def test_params_off_is_invisible(tmp_path):
    """关着时新增字段一个都不进 dump → params_hash 与加字段前逐位相同；开着时进。"""
    db = str(tmp_path / "g.db")
    off = SeedAdmitParams(db_path=db)
    assert not any(k.startswith(("rare_ref",)) for k in off.model_dump())
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


# ── 坐标对位那支（rare_ref_coord）────────────────────────────────────────────
def test_coord_admits_when_align_missing(tmp_path, monkeypatch):
    """现役对位缺这一格、坐标对位字 = 5-b 首位 → 放行坐标对位字，evidence 记 via=coord。"""
    r = _run(tmp_path, monkeypatch, rare=[REF, LIB], align=None, coord=REF, params=ON)
    assert r.admit and r.channel == "rare_ref" and r.char == REF and r.doubts == []
    assert r.evidence["rare_ref"] == {"rare": REF, "ref": REF, "lib": LIB, "cov": 0.95, "via": "coord"}


def test_coord_switch_off_and_params(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, rare=[REF, LIB], align=None, coord=REF,
             params={**ON, "rare_ref_coord": False})
    assert not r.admit and "rare_ref" not in r.evidence
    db = str(tmp_path / "g.db")
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    h = lambda p: params_hash(p, sp, pt)  # noqa: E731
    on = SeedAdmitParams(db_path=db, rare_ref=True)
    assert on.model_dump()["rare_ref_coord"] is True
    assert h(on) != h(SeedAdmitParams(db_path=db, rare_ref=True, rare_ref_coord=False))
    # rare_ref 关着时这个字段不进 dump
    assert "rare_ref_coord" not in SeedAdmitParams(db_path=db).model_dump()


@pytest.mark.parametrize("kw", [
    dict(rare=["〓"], coord="〓"),                            # 逐列本生僻字占位
    dict(rare=[REF], coord=""),                               # 坐标对位说是空格位
    dict(rare=[LIB, REF], coord=REF),                         # 5-b 首位不是坐标对位字
    dict(rare=["曰"], coord="曰", cands=(("日", 0.95),)),     # 字组里的字归 group_flow
    dict(rare=[REF], coord=REF, cands=(("日", 0.95),)),       # 库首位在字组里
    dict(rare=["裏"], coord="裏", cands=((LIB, 0.95), ("裡", 0.94))),   # 库候选里有坐标对位字的异体
    dict(rare=[REF], coord=REF, cands=((LIB, 0.85),)),        # 库首位覆盖度太低（页末、版心外的怪格）
])
def test_coord_blocked(tmp_path, monkeypatch, kw):
    r = _run(tmp_path, monkeypatch, align=None, params=ON, **kw)
    assert not r.admit and "rare_ref" not in r.evidence


def test_coord_not_used_when_align_present(tmp_path, monkeypatch):
    """现役对位有这一格（equal）时照旧只认现役对位，坐标对位不顶替。"""
    r = _run(tmp_path, monkeypatch, rare=[REF], align=(LIB, "equal"), coord=REF, params=ON)
    assert r.channel != "rare_ref"


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


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest


@pytest.mark.parametrize("doubt", ["ctx_guard_ref", "group_flow_ref_dissent", "group_flow_coord_dissent"])
def test_keep_ref_review_cells(doubt):
    """护栏拿整理本字拦下的格不由 rare_ref（两遍）按整理本字放回（vol18:115:6:3 刻「本」、整理本与 5-b 作「木」；
    本/木 在字组里，坐标那遍本就不碰，这里换不在字组里的一对测两遍）。"""
    from types import SimpleNamespace
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
    cid = f"{BOOK}:{PAGE}:{COL}:1"

    def run(keep, coord=None):
        out = [ColumnAdmit(col=COL, chars=[AdmitRec(id=cid, slot=1, char=LIB, doubts=["replace_align", doubt])])]
        mmap = {cid: SimpleNamespace(verdict="unsure", char=None, candidates=[(LIB, 0.98)], guard=None, cov=0.98)}
        amap = {} if coord else {cid: (REF, "replace")}
        n = sa._rare_ref_pass(out, mmap, amap, {cid: [REF]}, coord, keep_ref_review=keep)
        return n, out[0].chars[0]

    for coord in (None, {cid: REF}):
        n, r = run(True, coord)
        assert n == 0 and not r.admit and r.char == LIB
        if coord and doubt.startswith("group_flow"):
            continue                    # 坐标那遍本来就不碰 group_flow 降审格（`_rare_ref_coord_ok`）
        n, r = run(False, coord)
        assert n == 1 and r.char == REF and r.channel == "rare_ref"


def test_keep_ref_review_in_dump_with_rare_ref_only():
    on = SeedAdmitParams(rare_ref=True, lane_witness3=False, lane_coord=False, lane_seal=False)
    off = SeedAdmitParams(rare_ref=False, lane_witness3=False, lane_coord=False, lane_seal=False)
    assert "lane_keep_ref_review" in on.model_dump()
    assert "lane_keep_ref_review" not in off.model_dump()
