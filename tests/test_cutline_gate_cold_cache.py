# -*- coding: utf-8 -*-
"""顺序闸冷缓存不再静默放行（2026-09-28，C 道；CV 总管派单）。

`blocking_cutline_cases` 取切线用例要读列图缓存，缓存里没有的列会被**静默跳过**、
取用例抛异常时整个闸门返回空——两种情况字卡都会越过「先切线后字符」直接出来。
修法：先 materialize 列图；仍取不到 / 抛异常时，那几列里本该挡的多候选切点保守当阻塞
（只给字卡闸 `cut_pending` 用，切线面板要能画的用例，不混兜底）。
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from open_guji_cv.review import cards as C


def _store(cols):
    """cols: {(页, 列): [(k, 上格, 下格, 候选数, dis_unet)]}"""
    pages: dict = {}
    for (pg, col), cps in cols.items():
        cc = NS(col=col, ok=True, cut_candidates=[
            NS(k=k, slot_above=a, slot_below=b, escalate=False, chosen=0,
               candidates=[NS(dis_unet=d) for _ in range(n)]) for k, a, b, n, d in cps])
        pages.setdefault(pg, []).append(cc)

    class St:
        def read(self, book, step, key, kind):
            pg = int(key[1:])
            return NS(columns=pages[pg]) if pg in pages else None
    return St()


@pytest.fixture
def patched(monkeypatch):
    from open_guji_cv.console import deps
    from open_guji_cv.eval import touching as T
    state = {"cases": [], "raise": None, "unavailable": set()}

    def cases(*a, **k):
        if state["raise"]:
            raise state["raise"]
        return list(state["cases"])
    monkeypatch.setattr(T, "r2s_boundaries", cases)
    monkeypatch.setattr(T, "split_char_boundaries", lambda *a, **k: [])
    monkeypatch.setattr(T, "gold_ids", lambda: set())
    monkeypatch.setattr(deps, "event_log", lambda: NS(iter_all=lambda: []))
    monkeypatch.setattr(C, "_warm_column_images", lambda b, p, s: set(state["unavailable"]))
    return state


ST = _store({(3, 1): [(4, 4, 5, 2, 200)],        # 多候选 + 分歧大 → 该挡
             (3, 2): [(7, 7, 8, 2, 5)],          # 多候选但分歧小 → 不挡
             (5, 1): [(2, 2, 3, 1, 500)]})       # 单候选 → 不挡


def test_panel_case_still_blocks(patched):
    patched["cases"] = [{"id": "b:3:1:4", "page": 3, "col": 1, "slot_above": 4, "slot_below": 5, "bi": 4}]
    got = C.blocking_cutline_cases("b", [3, 5], ST, with_fallback=True)
    assert [c["id"] for c in got] == ["b:3:1:4"] and not got[0].get("fallback")


def test_exception_blocks_conservatively_not_silently(patched):
    """取用例抛异常：以前整个闸返回 []（静默放行），现在本该挡的切点照挡。"""
    patched["raise"] = RuntimeError("boom")
    got = C.blocking_cutline_cases("b", [3, 5], ST, with_fallback=True)
    assert [(c["page"], c["col"], c["slot_above"], c["slot_below"]) for c in got] == [(3, 1, 4, 5)]
    assert "boom" in got[0]["fallback"]
    pend = C.cut_pending("b", [3, 5], ST)
    assert set(pend) == {(3, 1, 4), (3, 1, 5)} and "保守挡下" in pend[(3, 1, 4)]


def test_unavailable_column_blocks_only_that_column(patched):
    patched["unavailable"] = {(3, 1)}
    got = C.blocking_cutline_cases("b", [3, 5], ST, with_fallback=True)
    assert [c["id"] for c in got] == ["b:3:1:4"] and got[0]["fallback"]
    patched["unavailable"] = {(3, 2)}             # 这列没有该挡的切点
    assert C.blocking_cutline_cases("b", [3, 5], ST, with_fallback=True) == []


def test_panel_scope_gets_no_fallback(patched):
    """切线面板（scope=blocking）拿用例画拖线卡：兜底用例没有几何，不能混进去。"""
    patched["raise"] = RuntimeError("boom")
    assert C.blocking_cutline_cases("b", [3, 5], ST) == []


def test_no_duplicate_when_panel_has_it(patched):
    patched["unavailable"] = {(3, 1)}
    patched["cases"] = [{"id": "b:3:1:4", "page": 3, "col": 1, "slot_above": 4, "slot_below": 5, "bi": 4}]
    got = C.blocking_cutline_cases("b", [3, 5], ST, with_fallback=True)
    assert len(got) == 1 and not got[0].get("fallback")


def test_warm_reports_unmaterializable(monkeypatch, tmp_path):
    """列图 materialize 抛错 → 记进「取不到」；已在缓存里的不重算。"""
    import open_guji_cv.products.cache as pc

    class Cache:
        def get(self, book, kind, key):
            return tmp_path / "x.png" if key.endswith("c01") else None
    monkeypatch.setattr(pc, "ImageCache", Cache)
    monkeypatch.setattr(C, "load_book", lambda b: NS(id=b))

    class Ctx:
        def __init__(self, *a, **k):
            pass

        def materialize(self, kind, key):
            raise FileNotFoundError("缺原图")
    import open_guji_cv.core.step as cs
    monkeypatch.setattr(cs, "RunContext", Ctx)
    assert C._warm_column_images("b", [3, 5], ST) == {(3, 2)}
