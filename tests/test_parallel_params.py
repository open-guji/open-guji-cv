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


class NumW(BaseModel):
    page: int
    pid: int


if "t_parw" not in KINDS:
    register_kind(ProductKindSpec(id="t_parw", title="暖机并行", storage="numeric", unit="page",
                                  schema=NumW))

if "t_step_parw" not in STEPS:
    @register_step
    class StepParW(Step):
        spec = StepSpec(id="t_step_parw", title="合成暖机并行步", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_parw",), params=ParamsP)

        def run_page(self, ctx, page):
            import os
            return {"t_parw": NumW(page=page, pid=os.getpid())}


def test_warm_first_runs_one_page_in_parent_then_forks(world, monkeypatch):
    """登记了 warm_first 的步：第一页在主进程跑（进程级缓存建好、fork 后共享），其余进 worker；
    各页都落盘、gc 冻结在跑完后解开。"""
    import gc
    import os

    from open_guji_cv.core import parallel
    monkeypatch.setitem(parallel.AUDITED, "t_step_parw",
                        parallel.ParallelAudit(mem_gb=0.01, note="测试", warm_first=True))
    book, _, tmp = world
    pl = Pipeline(id="t_parw_pl", title="t", steps=["t_step_parw"])
    pl.validate()
    eng = Engine(book, pl, store=ProductStore(tmp / "w" / "products"), cache=ImageCache(tmp / "w" / "cache"),
                 log=lambda s: None)
    rep = eng.run(pages=[1, 2, 3, 4], jobs=2)
    assert all(o.status == "ok" for o in rep.outcomes), rep.outcomes
    pids = [eng.ctx.product("t_parw", pg).pid for pg in (1, 2, 3, 4)]
    assert pids.count(os.getpid()) == 1          # 恰好一页在主进程
    assert gc.get_freeze_count() == 0            # 冻结解开了


def test_worker_pin_also_limits_loaded_openmp_runtimes():
    """影子模型（sklearn）的 OpenMP 运行库在主进程里已按核数初始化，fork 出的 worker 不压就 16 线程抢 4 核，
    每页从几秒拖到约 700 s（2026-10-21，vol09）。`_pin_threads` 要把已加载的 OpenMP 也压到 n。"""
    import subprocess
    import sys
    pytest.importorskip("sklearn")
    pytest.importorskip("threadpoolctl")
    code = ("import sklearn.ensemble, threadpoolctl\n"
            "from open_guji_cv.core.engine import _pin_threads\n"
            "_pin_threads(1, forked=False)\n"
            "omp = [i['num_threads'] for i in threadpoolctl.threadpool_info() if i['user_api'] == 'openmp']\n"
            "print(omp)\n"
            "assert omp and all(n == 1 for n in omp), omp\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
