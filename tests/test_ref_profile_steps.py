# -*- coding: utf-8 -*-
"""参校本属性 B 块（2026-11-08）：align_ref／row_segment 按册配置 `reference_profile` 逐页分支。

守几条：未声明的册指纹与产物不变；none 页 align_ref 不对位、记 note＋ref_kind；text 页不做坐标对位；
row_segment 无逐列参照的页不带格位先验、整册没有时 layout_prior 缺表不拦；自动配页不配这些页。"""
from __future__ import annotations

import json

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core import ref_profile as RP
from open_guji_cv.core.engine import ref_profile_token
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.recog import PageAlignRef
from open_guji_cv.steps import align_ref as AR
from open_guji_cv.steps import row_segment as RS
from open_guji_cv.steps import row_segment_coltext as CT
from open_guji_cv.steps import row_segment_pagemap as PM
from open_guji_cv.steps.align_ref import AlignRefParams

BOOK, PAGE, COL = "tbook", 1, 1
REF_TEXT = "文華殿大學士臣紀昀等奉敕撰欽定四庫全書總目卷一經部易類一"
COLUMN_CHARS = "文華殿大學士臣紀昀等奉敕撰"
REFS = [{"file": "ref.txt", "label": "ref", "quality": "best"}]


def _prof(raw, refs=REFS):
    return RP.load_reference_profile(raw, refs)


def _ctx(tmp_path, monkeypatch, profile=None):
    corpus = tmp_path / "ref.txt"
    corpus.write_text(REF_TEXT * 30, encoding="utf-8")
    kw = {"references": REFS}
    if profile is not None:
        kw["reference_profile"] = profile
    ctx = make_ctx(tmp_path, make_book(BOOK, **kw), monkeypatch=monkeypatch)
    ctx.params["align_ref"] = AlignRefParams(corpus=str(corpus))
    recs = [dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}")
            for i, ch in enumerate(COLUMN_CHARS)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    return ctx


# ── 指纹 ─────────────────────────────────────────────────────────────
def test_both_steps_are_aware_and_undeclared_adds_no_key():
    for sid in ("align_ref", "row_segment"):
        st = STEPS[sid]
        assert st.spec.ref_profile_aware
        assert ref_profile_token(st, make_book(), 5) is None
        # 别的步不吃这个属性：声明了也不加键
    other = next(s for k, s in STEPS.items() if not s.spec.ref_profile_aware)
    b = make_book(references=REFS, reference_profile=_prof("none"))
    assert ref_profile_token(other, b, 5) is None
    assert ref_profile_token(STEPS["align_ref"], b, 5) == "none:None"
    b = make_book(references=REFS, reference_profile=_prof({"default": "column",
                                                           "segments": [{"pages": [3], "kind": "text"}]}))
    assert ref_profile_token(STEPS["row_segment"], b, 3) == "text:0"
    assert ref_profile_token(STEPS["row_segment"], b, 4) is None       # column 页不加键


def test_ref_kind_not_serialized_when_empty():
    assert "ref_kind" not in PageAlignRef(page=1).model_dump()
    assert PageAlignRef(page=1, ref_kind="none").model_dump()["ref_kind"] == "none"


# ── align_ref ────────────────────────────────────────────────────────
def test_align_ref_undeclared_unchanged(tmp_path, monkeypatch, ws):
    ar = STEPS["align_ref"].run_page(_ctx(tmp_path, monkeypatch), PAGE)["align_ref"]
    assert ar.anchored and not ar.ref_kind


def test_align_ref_none_page_skips(tmp_path, monkeypatch, ws):
    ctx = _ctx(tmp_path, monkeypatch, _prof({"default": "column", "segments": [{"pages": [PAGE], "kind": "none"}]}))
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert not ar.anchored and ar.chars == []
    assert ar.note == "本页无参照（配置）" and ar.ref_kind == "none"
    assert not ar.coord and not ar.coord_note


def test_align_ref_text_page_aligns_without_coord(tmp_path, monkeypatch, ws):
    ctx = _ctx(tmp_path, monkeypatch, _prof("text"))
    ctx.params["align_ref"] = ctx.params["align_ref"].model_copy(update={"coord": "on"})
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored and ar.ref_kind == "text"
    assert not ar.coord and ar.coord_note == AR.REF_TEXT_COORD_NOTE


def test_align_ref_other_reference_not_supported_yet():
    refs = REFS + [{"file": "b.txt", "label": "b"}]
    b = make_book(references=refs, reference_profile=_prof({"default": "column",
                                                            "segments": [{"pages": [2], "kind": "text", "ref": "b"}]},
                                                           refs))
    assert AR._ref_kind(b, 1) == ""
    with pytest.raises(ValueError, match="references\\[0\\]"):
        AR._ref_kind(b, 2)


# ── row_segment ──────────────────────────────────────────────────────
def test_row_segment_prior_switches():
    assert RS._ref_has_column(make_book()) and not RS._ref_no_prior(make_book(), 1)
    b = make_book(references=REFS, reference_profile=_prof("none"))
    assert not RS._ref_has_column(b) and RS._ref_no_prior(b, 1)
    b = make_book(references=REFS, reference_profile=_prof({"default": "none",
                                                           "segments": [{"pages": ["3-4"], "kind": "column"}]}))
    assert RS._ref_has_column(b) and RS._ref_no_prior(b, 1) and not RS._ref_no_prior(b, 3)
    b = make_book(references=REFS, reference_profile=_prof("text"))
    assert not RS._ref_has_column(b)


def test_pagemap_skip_pages_and_fingerprint():
    assert PM.skip_pages(make_book(pages=[1, 2, 3])) == []
    b = make_book(references=REFS, pages=list(range(1, 8)),
                  reference_profile=_prof({"default": "column", "segments": [
                      {"pages": ["2-3"], "kind": "none"}, {"pages": [6], "kind": "text"}]}))
    assert PM.skip_pages(b) == [2, 3, 6]
    assert PM._with_skip("abcd", []) == "abcd"
    assert PM._with_skip("abcd", [2]) != "abcd" and PM._with_skip("abcd", [2]) != PM._with_skip("abcd", [3])
    with pytest.raises(ValueError, match="钉位表"):
        PM._check_pin_conflict("tbook", [1, 2], [2, 3])
    PM._check_pin_conflict("tbook", [1], [2, 3])


# ── 自动配页（column_text）──────────────────────────────────────────
NS, NCOL = 22, 9
CHARS = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結為霜"


def _grid(cols):
    g = np.full((NCOL, NS), 0.01, dtype=np.float32)
    for c, (st, n) in enumerate(cols):
        for k in range(st, st + n):
            g[c, k - 1] = 0.15
    return g


def test_coltext_build_skips_declared_pages(tmp_path):
    rng = np.random.default_rng(5)
    halves = [(f"KR_0001-{i + 1:02d}a", [int(x) for x in rng.integers(4, NS + 1, NCOL)]) for i in range(12)]
    text = lambda c, k: ["".join(CHARS[int(i)] for i in np.random.default_rng(k).integers(0, len(CHARS), n)) for n in c]
    path = tmp_path / "grid.txt"
    path.write_text("#@ header\n" + "".join(f"#@ {h}\n" + "".join(x + "\n" for x in text(c, k))
                                          for k, (h, c) in enumerate(halves)), encoding="utf-8")
    # 册首三页是参照里没有的总目（满页有字），其后各页依次对上半叶 0–11
    toc = [_grid([(1, NS)] * NCOL) for _ in range(3)]
    grids = toc + [_grid([(1, n) for n in c]) for _h, c in halves]
    pages = list(range(1, len(grids) + 1))
    base = CT.build("003", pages, grids, path, {}, "strict", NS, NCOL)
    d = CT.build("003", pages, grids, path, {}, "strict", NS, NCOL, skip=[1, 2, 3])
    got = {r["page"]: r["head"] for r in d["rows"]}
    assert all(got[p] is None for p in (1, 2, 3))
    assert all(got[p + 4] == h for p, (h, _c) in enumerate(halves))
    assert d["summary"]["bad_text_pages"] == [] and d["summary"]["ref_skip_pages"] == [1, 2, 3]
    assert d["summary"]["text_pages"] == base["summary"]["text_pages"] - 3
    assert not any(r["page"] in (1, 2, 3) for r in d["layout"])
    # skip 为空：与原来逐位相同
    again = CT.build("003", pages, grids, path, {}, "strict", NS, NCOL, skip=())
    assert json.dumps(again, sort_keys=True) == json.dumps(base, sort_keys=True)


def test_layout_prior_missing_book_only_blocks_undeclared():
    assert not RS._ref_declared(make_book())
    assert RS._ref_declared(make_book(references=REFS, reference_profile=_prof({"default": "column",
                                                                              "segments": [{"pages": [1], "kind": "none"}]})))
