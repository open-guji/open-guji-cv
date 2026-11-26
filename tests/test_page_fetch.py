# -*- coding: utf-8 -*-
"""字块按页取回（2026-11-25「字块随包存 R2」）：链指纹、缓存未命中先问 `core.derived.PAGE_FETCHER`、取不到照旧现算。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core import derived
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec, page_key, parse_key
from open_guji_cv.core.step import KINDS, STEPS, RunContext, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


class _N(BaseModel):
    page: int
    v: float


class _Q(BaseModel):
    pass


class _P(BaseModel):
    gain: float = 1.0


if "t_pf_a" not in KINDS:
    register_kind(ProductKindSpec(id="t_pf_a", title="A", storage="numeric", unit="page", schema=_N))
    register_kind(ProductKindSpec(id="t_pf_img", title="img", storage="image_cache", unit="page"))
    register_kind(ProductKindSpec(id="t_pf_b", title="B", storage="numeric", unit="page", schema=_N))

RENDERED: list[str] = []

if "t_pf_step_a" not in STEPS:
    @register_step
    class _A(Step):
        spec = StepSpec(id="t_pf_step_a", title="A", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_pf_a", "t_pf_img"), params=_P)

        def run_page(self, ctx, page):
            img = ctx.raw_page(page)
            ctx.cache.put(ctx.book.id, "t_pf_img", page_key(page), 255 - img)
            return {"t_pf_a": _N(page=page, v=float(img.mean()) * ctx.params_for(self).gain)}

        def render(self, ctx, kind_id, key):
            RENDERED.append(key)
            return 255 - ctx.raw_page(parse_key(key)[0])

    @register_step
    class _B(Step):
        spec = StepSpec(id="t_pf_step_b", title="B", version="1", unit="page",
                        consumes=("t_pf_a", "t_pf_img"), produces=("t_pf_b",), params=_Q)

        def run_page(self, ctx, page):
            img = ctx.image("t_pf_img", page_key(page))
            return {"t_pf_b": _N(page=page, v=float(img.mean()))}


@pytest.fixture
def world(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    rng = np.random.default_rng(0)
    for pg in (1, 2):
        cv2.imwrite(str(raw / f"{pg}.png"), rng.integers(0, 255, (40, 30), dtype=np.uint8))
    book = BookSpec(id="tpf", title="t", raw_dir=raw, dev_set=[1, 2])
    pl = Pipeline(id="tpf", title="t", steps=["t_pf_step_a", "t_pf_step_b"])
    pl.validate()
    store, cache = ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")
    monkeypatch.setattr(derived, "PAGE_KINDS", frozenset({"t_pf_img"}))
    monkeypatch.setattr(derived, "PAGE_FETCHER", None)
    monkeypatch.delenv("GUJI_PATCH_FETCH", raising=False)
    RENDERED.clear()
    return book, pl, store, cache


def _ctx(world, cache=None):
    book, pl, store, c = world
    return RunContext(book, store, cache or c, pipeline=pl, log=lambda s: None)


def test_chain_fingerprint_covers_upstream(world):
    book, pl, store, cache = world
    Engine(book, pl, store=store, cache=cache, log=lambda s: None).run(pages=[1])
    ctx = _ctx(world)
    fp = ctx.chain_fingerprint("t_pf_step_a", 1)
    assert fp and len(fp) == 16
    assert ctx.chain_fingerprint("t_pf_step_a", 2) is None          # 这一页没跑过：不取不传
    fpb = ctx.chain_fingerprint("t_pf_step_b", 1)
    assert fpb and fpb != fp                                       # 下游的链含上游
    Engine(book, pl, store=store, cache=cache, params={"t_pf_step_a": {"gain": 2.0}},
           log=lambda s: None).run(pages=[1])
    assert _ctx(world).chain_fingerprint("t_pf_step_a", 1) != fp   # 上游参数变了，链指纹变


def test_miss_asks_fetcher_then_falls_back(world, tmp_path):
    book, pl, store, cache = world
    Engine(book, pl, store=store, cache=cache, log=lambda s: None).run(pages=[1, 2])
    cold = ImageCache(tmp_path / "cold")                           # 新容器：没有缓存
    want = np.full((40, 30), 7, np.uint8)
    calls = []

    def fetch(book_id, kind_id, page, fp, c, stamp):
        calls.append((book_id, kind_id, page, fp))
        if page != 1:
            return False
        ok, buf = cv2.imencode(".png", want)
        c.put_bytes(book_id, kind_id, page_key(page), buf.tobytes(), stamp=stamp)
        return True

    derived.PAGE_FETCHER = fetch
    ctx = _ctx(world, cold)
    img = ctx.image("t_pf_img", page_key(1))
    assert (img == 7).all() and RENDERED == []                     # 取回的，不现算
    assert calls == [("tpf", "t_pf_img", 1, ctx.chain_fingerprint("t_pf_step_a", 1))]
    ctx.image("t_pf_img", page_key(2))                             # 取不到 → 现算
    assert RENDERED == ["p0002"]
    ctx.image("t_pf_img", page_key(2))
    assert len(calls) == 2                                         # 同一页只问一次


def test_producer_step_and_switch_do_not_fetch(world, tmp_path, monkeypatch):
    book, pl, store, cache = world
    Engine(book, pl, store=store, cache=cache, log=lambda s: None).run(pages=[1])
    calls = []
    derived.PAGE_FETCHER = lambda *a: calls.append(a) or False
    ctx = _ctx(world, ImageCache(tmp_path / "c1"))
    ctx.step_id = "t_pf_step_a"                                    # 产出它的那一步自己在跑：manifest 还是旧的
    ctx.image("t_pf_img", page_key(1))
    assert calls == []
    monkeypatch.setenv("GUJI_PATCH_FETCH", "0")
    ctx2 = _ctx(world, ImageCache(tmp_path / "c2"))
    ctx2.image("t_pf_img", page_key(1))
    assert calls == []
