# -*- coding: utf-8 -*-
"""矮格转人审(任意 slot)（`seed_admit.runt_cell_review`，overview#554）：只降级、缺省关、关时 params_hash 不变。自造数据。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import open_guji_cv.steps  # noqa: F401
import open_guji_cv.steps.seed_admit as sa
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1
PERIOD, N = 100.0, 3


def _cell(slot, h, **kw):
    d = dict(slot=slot, kind="char", raised=False, sub=None, flags=[], ink_ratio=0.2, y0=0.0, y1=float(h))
    return NS(**{**d, **kw})


def test_off_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert SeedAdmitParams().runt_cell_review is False
    assert "runt_cell_review" not in d and "runt_ratio" not in d and "runt_min_ink" not in d
    on = SeedAdmitParams(runt_cell_review=True).model_dump()
    assert on["runt_cell_review"] is True and on["runt_ratio"] == 0.6


def _run(tmp_path, monkeypatch, params, cells_by_slot, n_body=N, human=False, sub3=None):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    ctx = RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params}, log=lambda s: None)
    chars = ["山", "水", "木"]
    recs = [dict(slot=i + 1, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)], **({"sub": sub3} if sub3 and i == 2 else {}))
            for i, c in enumerate(chars)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=i + 1, align_char=c) for i, c in enumerate(chars)], col=COL))
    cells = NS(columns=[NS(col=COL, ok=True, period=PERIOD, n_body_slots=n_body,
                           cells=[_cell(s, h, **kw) for s, (h, kw) in cells_by_slot.items()])])
    real = sa._opt
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: cells if k == "cells" else real(c, k, pg))
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in page.columns for r in cc.chars}


SHORT = {1: (100, {}), 2: (100, {}), 3: (40, {})}


def test_default_off_changes_nothing(tmp_path, monkeypatch):
    base = _run(tmp_path, monkeypatch, SeedAdmitParams(), SHORT)
    assert all(r.admit for r in base.values())


def test_on_demotes_runt_tail_cell(tmp_path, monkeypatch):
    off = _run(tmp_path, monkeypatch, SeedAdmitParams(), SHORT)
    on = _run(tmp_path / "b", monkeypatch, SeedAdmitParams(runt_cell_review=True), SHORT)
    assert not on[3].admit and "runt_cell" in on[3].doubts and on[3].char == off[3].char
    assert on[3].evidence["runt_cell"] == {"h": 40.0, "period": 100.0}
    assert on[1].admit and on[2].admit
    assert sum(r.admit for r in on.values()) <= sum(r.admit for r in off.values())   # 只降级，0 格变放行


def test_mid_slot_runt_demoted_too(tmp_path, monkeypatch):
    """C 类:矮格不在末格(vol02 15:9:20 是 slot 20 而非 21)也要降级;其余格不动。"""
    cells = {1: (100, {}), 2: (40, {}), 3: (100, {})}
    off = _run(tmp_path, monkeypatch, SeedAdmitParams(), cells)
    on = _run(tmp_path / "b", monkeypatch, SeedAdmitParams(runt_cell_review=True), cells)
    assert not on[2].admit and "runt_cell" in on[2].doubts and on[2].char == off[2].char
    assert on[1].admit and on[3].admit
    assert sum(r.admit for r in on.values()) <= sum(r.admit for r in off.values())


def test_not_triggered_cases(tmp_path, monkeypatch):
    P = SeedAdmitParams(runt_cell_review=True)
    # 不矮 / 带 flag / raised / 无墨(空白格) / 正常格:都不动
    for cells in ({1: (100, {}), 2: (100, {}), 3: (70, {})},
                  {1: (100, {}), 2: (100, {}), 3: (40, {"flags": ["small"]})},
                  {1: (100, {}), 2: (100, {}), 3: (40, {"raised": True})},
                  {1: (100, {}), 2: (40, {"ink_ratio": 0.0}), 3: (100, {})},
                  {1: (100, {}), 2: (100, {}), 3: (100, {})}):
        got = _run(tmp_path / str(id(cells)), monkeypatch, P, cells)
        assert all(r.admit for r in got.values()), cells


def _runt_direct(monkeypatch, channel, h=14, ink=0.0):
    """直接喂 `_runt_cell_pass`：一列 3 格，slot3 为 a 夹注半格，通道由参数定。"""
    cells = NS(columns=[NS(col=1, ok=True, period=PERIOD, n_body_slots=3, cells=[
        _cell(1, 100), _cell(2, 100),
        _cell(3, h, sub="a", kind="jiazhu_a", ink_ratio=ink)])])
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: cells)
    mk = lambda slot, sub, ch: NS(slot=slot, sub=sub, admit=True, channel=ch, provenance="x", doubts=[], evidence={})
    recs = [mk(1, None, "match_ref"), mk(2, None, "match_ref"), mk(3, "a", channel)]
    n = sa._runt_cell_pass(None, 1, SeedAdmitParams(runt_cell_review=True), [NS(col=1, chars=recs)])
    return n, recs


def test_short_jiazhu_sub_demoted_zero_ink(monkeypatch):
    """列尾矮夹注半格(vol02:94:9:21a context；vol01:90:7:20a match_solo、墨 0.0)：降级。"""
    for ch in ("context", "match_solo"):
        n, recs = _runt_direct(monkeypatch, ch)
        assert n == 1 and not recs[2].admit and "runt_cell" in recs[2].doubts
        assert recs[0].admit and recs[1].admit


def test_short_jiazhu_sub_match_ref_and_normal_height_kept(monkeypatch):
    """match_ref（整理本对位字也同字，vol01:90 三格真「一」）与正常高度的夹注不动。"""
    n, recs = _runt_direct(monkeypatch, "match_ref")
    assert n == 0 and recs[2].admit
    n, recs = _runt_direct(monkeypatch, "context", h=100)
    assert n == 0 and recs[2].admit


import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
