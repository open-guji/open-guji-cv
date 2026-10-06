# -*- coding: utf-8 -*-
"""Step7 context 通道放行乱码的护栏（`context_garble_guard`，overview#427，C1 道）。

形态取自 vol04：列切窄 / 卷末印章被切成字格，字块不像任何刻例（库 cov 低）、码位罕用、
整列连成串，没有整理本或 OCR 背书，context 仍给 margin 高分放行。数据全是自造的产物。"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_chars, page_decision, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.recog import CoordRec, PageAlignRef
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _rare_run_ids

BOOK, PAGE, COL = "tbook", 1, 1


def _ctx(tmp_path, monkeypatch, **params):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    kwargs = {"seed_admit": SeedAdmitParams(**params)} if params else {}
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                      params=kwargs, log=lambda s: None)


def _run(ctx, cells, refs=None):
    """一列，`cells` 每项 `(context 字, 库 cov, 库 top 字)`；库都不定（unsure），context 都定了。
    `refs={slot: 坐标对位字}`。返回每格的 AdmitRec。"""
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=i + 1, verdict="unsure", cov=cov, wmax=0.0, candidates=[(top, cov)])
        for i, (_c, cov, top) in enumerate(cells)]))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(PAGE, BOOK, col=COL, recs=[
        dict(slot=i + 1, char=c, margin=1.0, source="context") for i, (c, _v, _t) in enumerate(cells)]))
    write_product(ctx, "cell_shrink", PAGE, char_index=page_chars(PAGE, BOOK, col=COL, recs=[
        dict(slot=i + 1, ink_ratio=0.3) for i in range(len(cells))]))
    coord = [CoordRec(id=f"{BOOK}:{PAGE}:{COL}:{s}", col=COL, slot=s, ref_char=ch)
             for s, ch in (refs or {}).items()]
    write_product(ctx, "align_ref", PAGE,
                  align_ref=PageAlignRef(page=PAGE, anchored=False, coord=coord, coord_cols=[COL]))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return [r for cc in sa.columns for r in cc.chars]


def test_off_admits_garble(tmp_path, monkeypatch):
    """前提：关着时乱码照放（否则后面的拦截测试是空转）。"""
    rs = _run(_ctx(tmp_path, monkeypatch, context_garble_guard=False),
              [("𬑹", 0.71, "𬑹"), ("理", 0.84, "理")])
    assert all(r.admit and r.channel == "context" for r in rs)


def test_low_cov_without_witness_blocked(tmp_path, monkeypatch):
    rs = _run(_ctx(tmp_path, monkeypatch), [("理", 0.84, "理"), ("理", 0.93, "理")])
    assert not rs[0].admit and "ctx_garble_shape" in rs[0].doubts and rs[0].char == "理"
    assert rs[1].admit and rs[1].channel == "context"


def test_witness_agreeing_spares_cell(tmp_path, monkeypatch):
    """坐标对位字与 context 字同 → 有背书，cov 再低也不拦；对位字不同不算背书。"""
    rs = _run(_ctx(tmp_path, monkeypatch), [("理", 0.80, "理"), ("理", 0.80, "理")],
              refs={1: "理", 2: "博"})
    assert rs[0].admit and rs[0].channel == "context"
    assert not rs[1].admit and "ctx_garble_shape" in rs[1].doubts


def test_rare_codepoint_needs_low_cov(tmp_path, monkeypatch):
    """罕用码位且 cov < 0.95 拦；㫖 这种本书常刻的扩展区字 cov 高，不拦。"""
    rs = _run(_ctx(tmp_path, monkeypatch, context_garble_run=0),
              [("𪜊", 0.93, "𪜊"), ("㫖", 0.98, "㫖")])
    assert not rs[0].admit and "ctx_garble_rare" in rs[0].doubts
    assert rs[1].admit and rs[1].channel == "context"


def test_rare_run_blocks_common_chars_in_garbled_column(tmp_path, monkeypatch):
    """整列切坏：库 top 罕用码位连成串，中间夹着的常用字（cov 不低）也拦。"""
    cells = [("𬑹", 0.96, "𬑹"), ("小", 0.93, "𢍺"), ("是", 0.93, "𠳋"), ("世", 0.93, "𭦋"), ("讠", 0.96, "讠")]
    rs = _run(_ctx(tmp_path, monkeypatch), cells)
    assert [r.admit for r in rs] == [False] * 5
    assert "ctx_garble_run" in rs[3].doubts
    rs = _run(_ctx(tmp_path / "off", monkeypatch, context_garble_run=0), cells)
    assert rs[3].admit and rs[3].channel == "context"


def test_rare_run_window():
    from types import SimpleNamespace as NS
    recs = [NS(id=str(i), char=None, candidates=[(ch, 0.9)]) for i, ch in enumerate("之𬑹而不𢍺以爲𠳋方")]
    # 3 个罕用码位相隔 3 格：只有正中那格的 ±3 窗口凑得齐（k=3）；k=4 凑不齐；k=0 关
    assert _rare_run_ids(recs, 3) == frozenset({"4"})
    assert _rare_run_ids(recs, 4) == frozenset()
    assert _rare_run_ids(recs, 0) == frozenset()
    sparse = [NS(id=str(i), char=None, candidates=[(ch, 0.9)]) for i, ch in enumerate("㫖之而不以爲方之而㫖")]
    assert _rare_run_ids(sparse, 3) == frozenset()
