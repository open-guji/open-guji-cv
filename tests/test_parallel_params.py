# -*- coding: utf-8 -*-
"""GUJI-580：`--jobs>1` 时 worker 必须拿到和主进程同一份参数与产物目录。

以前 `_parallel_worker_init` 只收 book/pipeline 的 id，在子进程里重新加载、
建一个空参数的 ctx：CLI `--params` 与管线 yaml 的 `params:` 全丢，产物按缺省
参数算，manifest 的指纹却记的是覆盖后的参数。这里用一个合成的 parallel_safe
步，比较串行与并行（jobs=2）跑出的产物。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401  —— 注册 raw_page 等产物种类
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


class NumP(BaseModel):
    page: int
    gain: float
    offset: float


class ParamsP(BaseModel):
    gain: float = 1.0
    offset: float = 0.0


if "t_par" not in KINDS:
    register_kind(ProductKindSpec(id="t_par", title="并行", storage="numeric", unit="page",
                                  schema=NumP))

if "t_step_par" not in STEPS:
    @register_step
    class StepPar(Step):
        spec = StepSpec(id="t_step_par", title="合成并行步", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_par",), params=ParamsP,
                        parallel_safe=True)

        def run_page(self, ctx, page):
            p = ctx.params_for(self)
            return {"t_par": NumP(page=page, gain=p.gain, offset=p.offset)}


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rng = np.random.default_rng(0)
    for pg in (1, 2, 3, 4):
        cv2.imwrite(str(raw / f"{pg}.png"), rng.integers(0, 255, (20, 20), dtype=np.uint8))
    # 册与管线都不在注册表里：worker 若还按 id 重新加载就会直接失败。
    book = BookSpec(id="tpar", title="t", raw_dir=raw)
    pl = Pipeline(id="t_par_pl", title="t", steps=["t_step_par"],
                  params={"t_step_par": {"offset": 5.0}})
    pl.validate()
    return book, pl, tmp_path


def _run(world, sub, jobs, params):
    book, pl, tmp = world
    store = ProductStore(tmp / sub / "products")
    eng = Engine(book, pl, store=store, cache=ImageCache(tmp / sub / "cache"),
                 params=params, log=lambda s: None)
    rep = eng.run(pages=[1, 2, 3, 4], jobs=jobs)
    assert all(o.status == "ok" for o in rep.outcomes), rep.outcomes
    out = {pg: eng.ctx.product("t_par", pg) for pg in (1, 2, 3, 4)}
    fps = {pg: eng.store.manifest(book.id, "t_step_par").get(f"p{pg:04d}").fingerprint
           for pg in (1, 2, 3, 4)}
    return out, fps


def test_parallel_keeps_cli_and_pipeline_params(world):
    params = {"t_step_par": {"gain": 3.0}}
    ser, ser_fp = _run(world, "ser", 1, params)
    par, par_fp = _run(world, "par", 2, params)
    for pg in (1, 2, 3, 4):
        assert par[pg].gain == 3.0          # 调用方覆盖（CLI --params）
        assert par[pg].offset == 5.0        # 管线 yaml 的 params:
        assert par[pg] == ser[pg]
    assert par_fp == ser_fp


def test_parallel_writes_to_engine_store(world):
    """worker 只算不写盘，但读上游要走主进程给的产物根目录，不是缺省 products/。"""
    _, _, tmp = world
    _run(world, "par2", 2, None)
    assert (tmp / "par2" / "products" / "tpar" / "t_step_par").is_dir()
