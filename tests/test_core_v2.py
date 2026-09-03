# -*- coding: utf-8 -*-
"""四个抽象 P0：Step / Product / 指纹 / stale / 缓存 / DAG。

合成两步（t_step_a → t_step_b）在 tmp 目录里跑，不碰 output/。
末尾一条集成测试跑真实 keben_body_v2 的第 24 页，缺原图就跳过。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401  —— 注册 raw_page 等产物种类与 v2 五步
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import BLOCKED, FAILED, FRESH, MISSING, STALE, Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import (ProductKindSpec, StepSpec, cell_key, column_key, page_key,
                                    parse_key)
from open_guji_cv.core.step import KINDS, STEPS, RunContext, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent


# ── 合成种类与步骤 ───────────────────────────────────────────────────
class NumA(BaseModel):
    page: int
    mean: float


class NumB(BaseModel):
    page: int
    doubled: float
    img_shape: tuple[int, int]


if "t_a" not in KINDS:
    register_kind(ProductKindSpec(id="t_a", title="A", storage="numeric", unit="page", schema=NumA))
    register_kind(ProductKindSpec(id="t_b", title="B", storage="numeric", unit="page", schema=NumB))
    register_kind(ProductKindSpec(id="t_img", title="img", storage="image_cache", unit="page"))


class ParamsA(BaseModel):
    gain: float = 1.0
    fail_page: int | None = None


class ParamsB(BaseModel):
    pass


if "t_step_a" not in STEPS:
    @register_step
    class StepA(Step):
        spec = StepSpec(id="t_step_a", title="合成 A", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_a", "t_img"), params=ParamsA)

        def run_page(self, ctx, page):
            p = ctx.params_for(self)
            if p.fail_page == page:
                raise RuntimeError("故意失败")
            img = ctx.raw_page(page)
            ctx.cache.put(ctx.book.id, "t_img", page_key(page), 255 - img)
            return {"t_a": NumA(page=page, mean=float(img.mean()) * p.gain)}

        def render(self, ctx, kind_id, key):
            return 255 - ctx.raw_page(parse_key(key)[0])

    @register_step
    class StepB(Step):
        spec = StepSpec(id="t_step_b", title="合成 B", version="1", unit="page",
                        consumes=("t_a", "t_img"), produces=("t_b",), params=ParamsB)

        def run_page(self, ctx, page):
            a = ctx.product("t_a", page)
            img = ctx.image("t_img", page_key(page))
            return {"t_b": NumB(page=page, doubled=a.mean * 2, img_shape=img.shape[:2])}


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rng = np.random.default_rng(0)
    for pg in (1, 2, 3):
        cv2.imwrite(str(raw / f"{pg}.png"), rng.integers(0, 255, (40, 30), dtype=np.uint8))
    book = BookSpec(id="tb", title="t", raw_dir=raw, dev_set=[1, 2])
    pl = Pipeline(id="t", title="t", steps=["t_step_a", "t_step_b"])
    pl.validate()
    store = ProductStore(tmp_path / "products")
    cache = ImageCache(tmp_path / "cache")
    return book, pl, store, cache, raw


def make_engine(world, params=None):
    book, pl, store, cache, _ = world
    return Engine(book, pl, store=store, cache=cache, params=params, log=lambda s: None)


# ── 键 ───────────────────────────────────────────────────────────────
def test_keys_roundtrip():
    assert page_key(42) == "p0042"
    assert parse_key(column_key(42, 3)) == (42, 3, None)
    assert parse_key(cell_key(42, 3, -1)) == (42, 3, -1)
    with pytest.raises(ValueError):
        parse_key("x")


# ── DAG ──────────────────────────────────────────────────────────────
def test_pipeline_dag(world):
    _, pl, _, _, _ = world
    assert pl.upstream("t_step_b") == ["t_step_a"]
    assert pl.downstream("t_step_a") == ["t_step_b"]
    assert {(a, b) for a, b, _ in pl.edges()} == {("t_step_a", "t_step_b")}
    assert pl.slice("t_step_b") == ["t_step_b"]
    bad = Pipeline(id="bad", title="", steps=["t_step_b"])
    with pytest.raises(ValueError):
        bad.validate()


# ── 产物仓 ───────────────────────────────────────────────────────────
def test_store_roundtrip_is_deterministic(tmp_path):
    st = ProductStore(tmp_path)
    _, sha1 = st.write("b", "s", "p0001", {"t_a": NumA(page=1, mean=1.5)})
    _, sha2 = st.write("b", "s", "p0001", {"t_a": NumA(page=1, mean=1.5)})
    assert sha1 == sha2
    assert st.read("b", "s", "p0001", "t_a") == NumA(page=1, mean=1.5)
    assert st.read("b", "s", "p0001", "t_b") is None
    assert st.keys("b", "s") == ["p0001"]


# ── 引擎：跑 / 跳过 / 过期 / 失败 ────────────────────────────────────
def test_engine_run_skip_and_stale(world):
    book, pl, store, cache, raw = world
    eng = make_engine(world)
    rep = eng.run()
    assert rep.counts() == {"t_step_a": {"ok": 2, "skipped": 0, "failed": 0},
                            "t_step_b": {"ok": 2, "skipped": 0, "failed": 0}}
    b = store.read("tb", "t_step_b", "p0001", "t_b")
    assert b.img_shape == (40, 30)

    # 再跑一遍：全部新鲜 → 跳过
    rep = eng.run()
    assert all(o.status == "skipped" for o in rep.outcomes)
    st = eng.status()
    assert st["steps"]["t_step_a"]["counts"][FRESH] == 2
    assert st["steps"]["t_step_b"]["counts"][FRESH] == 2
    assert 3 not in st["steps"]["t_step_a"]["pages"]          # dev_set 只有 1、2
    assert eng.status(pages=[3])["steps"]["t_step_a"]["pages"][3]["status"] == MISSING

    # 改 A 的参数 → A、B 都过期；只重跑 A 后 B 仍过期（上游 sha 变了）
    eng2 = make_engine(world, params={"t_step_a": {"gain": 2.0}})
    st = eng2.status()
    assert st["steps"]["t_step_a"]["counts"][STALE] == 2
    assert st["steps"]["t_step_b"]["counts"][STALE] == 2
    eng2.run(steps=["t_step_a"])
    st = eng2.status()
    assert st["steps"]["t_step_a"]["counts"][FRESH] == 2
    assert st["steps"]["t_step_b"]["counts"][STALE] == 2
    eng2.run(steps=["t_step_b"])
    assert eng2.status()["steps"]["t_step_b"]["counts"][FRESH] == 2
    assert store.read("tb", "t_step_b", "p0001", "t_b").doubled == pytest.approx(
        store.read("tb", "t_step_a", "p0001", "t_a").mean * 2)

    # 改原图第 1 页 → 只有第 1 页过期
    time.sleep(0.01)
    img = cv2.imread(str(raw / "1.png"), 0)
    cv2.imwrite(str(raw / "1.png"), 255 - img)
    st = eng2.status()
    assert st["steps"]["t_step_a"]["pages"][1]["status"] == STALE
    assert st["steps"]["t_step_a"]["pages"][2]["status"] == FRESH
    assert st["steps"]["t_step_b"]["pages"][1]["status"] == STALE


def test_engine_records_failure_and_blocks_downstream(world):
    eng = make_engine(world, params={"t_step_a": {"fail_page": 2}})
    rep = eng.run()
    assert rep.counts()["t_step_a"] == {"ok": 1, "skipped": 0, "failed": 1}
    st = eng.status()
    assert st["steps"]["t_step_a"]["pages"][2]["status"] == FAILED
    assert "故意失败" in st["steps"]["t_step_a"]["pages"][2]["error"]
    assert st["steps"]["t_step_b"]["pages"][2]["status"] == BLOCKED
    assert st["steps"]["t_step_b"]["pages"][1]["status"] == FRESH
    # 上游失败的页在 manifest 里留了记录
    m = eng.store.manifest("tb", "t_step_a").get("p0002")
    assert m.status == "failed"


def test_force_reruns_fresh_pages(world):
    eng = make_engine(world)
    eng.run()
    rep = eng.run(force=True)
    assert all(o.status == "ok" for o in rep.outcomes)


# ── 图像缓存 ─────────────────────────────────────────────────────────
def test_cache_materialize_regenerates(world):
    book, pl, store, cache, _ = world
    eng = make_engine(world)
    eng.run()
    p = cache.path("tb", "t_img", "p0001")
    assert p.exists()
    p.unlink()
    ctx = RunContext(book, store, cache, log=lambda s: None)
    img = ctx.image("t_img", "p0001")
    assert img.shape == (40, 30) and p.exists()
    n_bytes, n_files = cache.usage()
    assert n_files == 2 and n_bytes > 0
    freed = cache.prune(limit_bytes=0)
    assert freed == n_bytes and cache.usage()[1] == 0


def test_engine_rejects_image_kind_returned_as_numeric(world):
    book, pl, store, cache, _ = world

    class Bad(Step):
        spec = StepSpec(id="t_bad", title="", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_img",), params=ParamsB)

        def run_page(self, ctx, page):
            return {"t_img": NumA(page=page, mean=0)}

    STEPS["t_bad"] = Bad()
    try:
        eng = Engine(book, Pipeline(id="x", title="", steps=["t_bad"]), store=store, cache=cache,
                     log=lambda s: None)
        rep = eng.run(pages=[1])
        assert rep.outcomes[0].status == "failed" and "图像类" in rep.outcomes[0].error
    finally:
        STEPS.pop("t_bad", None)


# ── 真实链路（有原图才跑）────────────────────────────────────────────
RAW_24 = REPO / "data_full" / "zongmu" / "vol01" / "24.png"


@pytest.mark.skipif(not RAW_24.exists(), reason="需要 data_full/zongmu/vol01/24.png")
def test_keben_body_v2_on_vol01_page24(tmp_path):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import load_pipeline
    pl = load_pipeline("keben_body_v2")
    book = load_book("vol01")
    store, cache = ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")
    eng = Engine(book, pl, store=store, cache=cache, log=lambda s: None)
    rep = eng.run(pages=[24])
    assert not rep.to_dict()["failed"], rep.to_dict()["failed"]

    borders = store.read("vol01", "border_detect", "p0024", "borders")
    assert len(borders.verticals) == book.expected_cols + 1
    gate = store.read("vol01", "column_gate", "p0024", "gate_manifest")
    assert gate.admitted and gate.period and gate.ref_w
    cells = store.read("vol01", "row_segment", "p0024", "cells")
    assert sum(1 for c in cells.columns if c.ok) == 9
    assert all(len(c.cells) == book.chars_per_line for c in cells.columns if c.ok)
    chars = store.read("vol01", "cell_shrink", "p0024", "char_index")
    n = sum(c.n_instances for c in chars.columns)
    assert n > 150
    W, H = borders.width, borders.height
    for col in chars.columns:
        for ch in col.chars:
            x0, y0, x1, y1 = ch.bbox_page
            assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H
            assert ch.patch_key is None or cache.path("vol01", "char_patch", ch.patch_key).exists()
    # 第二遍全跳过；删掉缓存后 Step4 的字块能现算回来
    rep = eng.run(pages=[24])
    assert all(o.status == "skipped" for o in rep.outcomes)
    key = next(ch.patch_key for col in chars.columns for ch in col.chars if ch.patch_key)
    cache.path("vol01", "char_patch", key).unlink()
    ctx = RunContext(book, store, cache, log=lambda s: None)
    assert ctx.image("char_patch", key).size > 0
