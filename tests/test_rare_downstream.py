# -*- coding: utf-8 -*-
"""5-b 生僻字候选接进下游（2026-09-28，D 道 overview#126）。

`rare_candidates` 作为**带开关的可选上游**（`StepSpec.optional_consumes_when`）
接进 `align_ref`（锚定载体）、`context_decide`（候选池）、`seed_admit`（只记两路
是否一致）。这里守三件事：

1. 开关关着（缺省）时，5-b 产物在场也**不进指纹、不传过期**，参数哈希与加字段
   之前一样——四庫等早有 5-b 产物的书不能因为这次改代码整书 Step5-d～7 重跑；
2. 开关开了，5-b 的字真的进了载体 / 候选池 / 证据；
3. `seed_admit` 只记、不新增放行通道。
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import FRESH, STALE, Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec, live_optional_consumes
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.recog import ColumnRare, PageRare, RareCand, RareRec
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.align_ref import (AlignRefParams, rare_topk_map, rrf_carrier,
                                          slots_from_evidence)
from open_guji_cv.steps.context_decide import ContextDecideParams, rare_priors
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _rare_agree

BOOK, PAGE, COL = "tbook", 1, 1


def page_rare(page: int, book: str, cands: dict[int, list[str]], col: int = 1) -> PageRare:
    """`rare_candidates` 产物：{slot: [候选字…]}，分数随手给（下游只看名次）。"""
    recs = [RareRec(id=f"{book}:{page}:{col}:{s}", slot=s,
                    candidates=[RareCand(char=c, score=0.9 - 0.01 * i, font="emb")
                                for i, c in enumerate(cs)])
            for s, cs in cands.items()]
    return PageRare(page=page, columns=[ColumnRare(col=col, ok=True, chars=recs)])


# ── 声明 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sid,field", [("align_ref", "rare_topk"),
                                       ("context_decide", "rare_topk"),
                                       ("seed_admit", "rare_agree")])
def test_declared_as_gated_optional_upstream(sid, field):
    spec = STEPS[sid].spec
    assert "rare_candidates" in spec.optional_consumes
    assert ("rare_candidates", field) in spec.optional_consumes_when
    assert "rare_candidates" not in spec.consumes
    off = spec.params()
    assert "rare_candidates" not in live_optional_consumes(spec, off)
    on = off.model_copy(update={field: 5 if field == "rare_topk" else True})
    assert "rare_candidates" in live_optional_consumes(spec, on)


@pytest.mark.parametrize("P,kw,fields", [
    (AlignRefParams, {"rare_topk": 5}, ("rare_topk",)),
    (ContextDecideParams, {"rare_topk": 5}, ("rare_topk", "rare_weight")),
    (SeedAdmitParams, {"rare_agree": True}, ("rare_agree",)),
])
def test_switch_off_keeps_params_dump_unchanged(P, kw, fields):
    """关着时新字段不进 dump → `params_hash` 与加字段之前逐位相同（产物不过期）。"""
    off = P()
    assert not any(f in off.model_dump(mode="json") for f in fields)
    on = P(**kw)
    assert all(f in on.model_dump(mode="json") for f in fields)


# ── 引擎：开关关着不进指纹、不传过期 ────────────────────────────────────
class _NumA(BaseModel):
    page: int
    v: float


class _NumC(BaseModel):
    page: int
    saw_a: bool


class _ParamsA(BaseModel):
    gain: float = 1.0


class _ParamsC(BaseModel):
    use_a: bool = False


if "t_rare_a" not in KINDS:
    register_kind(ProductKindSpec(id="t_rare_a", title="A", storage="numeric", unit="page", schema=_NumA))
    register_kind(ProductKindSpec(id="t_rare_c", title="C", storage="numeric", unit="page", schema=_NumC))

if "t_rare_step_a" not in STEPS:
    @register_step
    class _StepA(Step):
        spec = StepSpec(id="t_rare_step_a", title="A", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_rare_a",), params=_ParamsA)

        def run_page(self, ctx, page):
            return {"t_rare_a": _NumA(page=page, v=ctx.params_for(self).gain)}

    @register_step
    class _StepC(Step):
        spec = StepSpec(id="t_rare_step_c", title="C", version="1", unit="page",
                        consumes=("raw_page",), optional_consumes=("t_rare_a",),
                        optional_consumes_when=(("t_rare_a", "use_a"),),
                        produces=("t_rare_c",), params=_ParamsC)

        def run_page(self, ctx, page):
            return {"t_rare_c": _NumC(page=page, saw_a=ctx.params_for(self).use_a)}


def _engine(tmp_path, params=None):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    cv2.imwrite(str(raw / "1.png"), np.zeros((20, 20), np.uint8))
    book = BookSpec(id="tb", title="t", raw_dir=raw, dev_set=[1])
    pl = Pipeline(id="t", title="t", steps=["t_rare_step_a", "t_rare_step_c"])
    pl.validate()
    return Engine(book, pl, store=ProductStore(tmp_path / "products"),
                  cache=ImageCache(tmp_path / "cache"), params=params, log=lambda s: None)


def test_register_rejects_gate_on_undeclared_kind():
    with pytest.raises(ValueError, match="optional_consumes_when"):
        @register_step
        class _Bad(Step):
            spec = StepSpec(id="t_rare_bad", title="bad", version="1", unit="page",
                            consumes=("raw_page",), optional_consumes_when=(("t_rare_a", "use_a"),),
                            produces=("t_rare_c",), params=_ParamsC)

            def run_page(self, ctx, page):
                return {}


def test_gated_upstream_off_stays_out_of_fingerprint_and_staleness(tmp_path):
    eng = _engine(tmp_path)
    eng.run(pages=[1])
    step_c = STEPS["t_rare_step_c"]
    assert "t_rare_a" not in eng.upstream_shas(step_c, 1)
    # 上游 A 换参数重跑：C 关着开关，不读 A → 仍新鲜，也不被标 upstream_stale
    eng2 = _engine(tmp_path, params={"t_rare_step_a": {"gain": 2.0}})
    eng2.run(pages=[1], steps=["t_rare_step_a"])
    st = eng2.status(pages=[1])["steps"]["t_rare_step_c"]["pages"][1]
    assert st["status"] == FRESH and not st["upstream_stale"]


def test_gated_upstream_on_behaves_like_optional_upstream(tmp_path):
    on = {"t_rare_step_c": {"use_a": True}}
    eng = _engine(tmp_path, params=on)
    eng.run(pages=[1])
    assert "t_rare_a" in eng.upstream_shas(STEPS["t_rare_step_c"], 1)
    eng2 = _engine(tmp_path, params={**on, "t_rare_step_a": {"gain": 2.0}})
    eng2.run(pages=[1], steps=["t_rare_step_a"])
    assert eng2.status(pages=[1])["steps"]["t_rare_step_c"]["pages"][1]["status"] == STALE


# ── align_ref：5-b 候选进锚定载体 ────────────────────────────────────────
def test_rare_topk_map_uses_rank_and_dedupes():
    pr = page_rare(PAGE, BOOK, {1: ["甲", "甲", "乙", "丙"], 2: []})
    assert rare_topk_map(pr, 2) == {f"{BOOK}:{PAGE}:{COL}:1": ["甲", "乙"]}
    assert rare_topk_map(pr, 0) == {} and rare_topk_map(None, 5) == {}


def test_rrf_carrier_prefers_cnn_on_ties_and_agreement_otherwise():
    # 像素首位 a、CNN 首位 b，互为对方第二名 → 同分，CNN 名次靠前的赢
    assert rrf_carrier([("a", 0.99), ("b", 0.98)], ["b", "a"]) == "b"
    # CNN 首位不在像素候选里、像素首位是 CNN 第二名 → 两路都认的 a 赢
    assert rrf_carrier([("a", 0.99)], ["z", "a"]) == "a"
    assert rrf_carrier([], ["z"]) == "z" and rrf_carrier([], []) is None


def test_slots_unchanged_without_rare_and_same_cells_never_touched():
    recs = [dict(slot=1, verdict="same", char="文", cov=0.999, candidates=[("文", 0.999)]),
            dict(slot=2, verdict="unsure", cov=0.97, candidates=[("大", 0.97), ("太", 0.96)])]
    pm = page_match(PAGE, BOOK, recs=recs)
    base = slots_from_evidence(pm, None)
    assert slots_from_evidence(pm, None, {}) == base
    assert [s[-1] for s in base] == ["文", "大"]
    rare = {f"{BOOK}:{PAGE}:{COL}:1": ["丈"], f"{BOOK}:{PAGE}:{COL}:2": ["太", "犬"]}
    assert [s[-1] for s in slots_from_evidence(pm, None, rare)] == ["文", "太"]


REF_TEXT = "文華殿大學士臣紀昀等奉敕撰欽定四庫全書總目卷一經部易類一"
COLUMN = "文華殿大學士臣紀昀等奉敕撰"
WRONG = "丈莘展太覺土巨組盷寺秦勑僎"   # 每格像素首位都错成一个形近字


def _ctx_bad_pixels(tmp_path, monkeypatch, *, rare_topk: int):
    corpus = tmp_path / "ref.txt"
    corpus.write_text(REF_TEXT * 30, encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    ctx.params["align_ref"] = AlignRefParams(corpus=str(corpus), rare_topk=rare_topk, lib_gate=False)
    recs = [dict(slot=i + 1, verdict="unsure", cov=0.97, candidates=[(w, 0.97), (c, 0.95)])
            for i, (c, w) in enumerate(zip(COLUMN, WRONG))]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs))
    write_product(ctx, "rare_candidates", PAGE, rare_candidates=page_rare(
        PAGE, BOOK, {i + 1: [c, w] for i, (c, w) in enumerate(zip(COLUMN, WRONG))}))
    return ctx


def test_align_ref_off_ignores_rare_product(tmp_path, monkeypatch, ws):
    ctx = _ctx_bad_pixels(tmp_path, monkeypatch, rare_topk=0)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not ar.anchored, "关着开关却读了 5-b：像素首位全错的列不该锚得上"


def test_align_ref_on_anchors_with_rare_carrier(tmp_path, monkeypatch, ws):
    ctx = _ctx_bad_pixels(tmp_path, monkeypatch, rare_topk=5)
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, ar.note
    got = "".join(c.align_char for c in sorted(ar.chars, key=lambda c: c.slot))
    assert got == COLUMN
    assert all(c.align_op == "equal" for c in ar.chars)


# ── context_decide / seed_admit ──────────────────────────────────────────
def test_rare_priors_by_rank_sum_to_one():
    pr = rare_priors(["甲", "乙", "丙"])
    assert [c for c, _ in pr] == ["甲", "乙", "丙"]
    assert abs(sum(w for _, w in pr) - 1.0) < 1e-9
    assert pr[0][1] > pr[1][1] > pr[2][1]
    assert rare_priors([]) == []


def test_rare_agree_record():
    from open_guji_cv.products.kinds.recog import MatchRec
    same = MatchRec(id="x", slot=1, verdict="same", char="文", cov=0.999, candidates=[("文", 0.999)])
    uns = MatchRec(id="y", slot=2, verdict="unsure", cov=0.97, candidates=[("大", 0.97)])
    assert _rare_agree(same, ["文", "丈"]) == {"pix": "文", "cnn": "文", "agree": True}
    assert _rare_agree(uns, ["太"]) == {"pix": "大", "cnn": "太", "agree": False}
    assert _rare_agree(uns, None)["agree"] is None
