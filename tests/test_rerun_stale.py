# -*- coding: utf-8 -*-
"""GUJI-578：`guji rerun --stale` 只跑显式失效的页及其下游。合成两步，不碰真书。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec, page_key
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.ops import rerun_stale as RS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


class NumR(BaseModel):
    page: int
    v: float


class PR(BaseModel):
    k: float = 1.0


CALLS: list[tuple[str, int]] = []

if "t_rs_a" not in KINDS:
    register_kind(ProductKindSpec(id="t_rs_a", title="a", storage="numeric", unit="page", schema=NumR))
    register_kind(ProductKindSpec(id="t_rs_b", title="b", storage="numeric", unit="page", schema=NumR))

if "t_rs_step_a" not in STEPS:
    @register_step
    class RA(Step):
        spec = StepSpec(id="t_rs_step_a", title="a", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_rs_a",), params=PR)

        def run_page(self, ctx, page):
            CALLS.append(("a", page))
            return {"t_rs_a": NumR(page=page, v=float(ctx.raw_page(page).mean()))}

    @register_step
    class RB(Step):
        spec = StepSpec(id="t_rs_step_b", title="b", version="1", unit="page",
                        consumes=("t_rs_a",), produces=("t_rs_b",), params=PR)

        def run_page(self, ctx, page):
            CALLS.append(("b", page))
            return {"t_rs_b": NumR(page=page, v=ctx.product("t_rs_a", page).v * 2)}


@pytest.fixture
def eng(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in (1, 2, 3):
        cv2.imwrite(str(raw / f"{pg}.png"), np.full((10, 10), pg * 10, np.uint8))
    book = BookSpec(id="trs", title="t", raw_dir=raw)
    pl = Pipeline(id="trs", title="t", steps=["t_rs_step_a", "t_rs_step_b"])
    pl.validate()
    e = Engine(book, pl, store=ProductStore(tmp_path / "p"), cache=ImageCache(tmp_path / "c"),
               log=lambda s: None)
    e.run(pages=[1, 2, 3])
    CALLS.clear()
    return e


def _steps(e):
    return lambda first, to: e.pipeline.slice(first, to)


def test_nothing_invalidated_runs_nothing(eng):
    p, rep = RS.run(eng, _steps(eng), log=lambda s: None)
    assert rep is None and not p.by_step and CALLS == []


def test_only_invalidated_pages_and_downstream(eng):
    eng.store.manifest("trs", "t_rs_step_a").invalidate(page_key(2), "人裁落定")
    eng.store.manifest("trs", "t_rs_step_b").invalidate(page_key(3), "切线裁决")
    p, rep = RS.run(eng, _steps(eng), log=lambda s: None)
    assert p.by_step == {"t_rs_step_a": [2], "t_rs_step_b": [3]}
    # a 只重跑 p2；b 只算 p3（自己失效）。p2 交给 b 判，但 a 的产物逐字节没变，
    # b 的指纹仍新鲜、跳过；p1 一页都不碰
    assert sorted(CALLS) == [("a", 2), ("b", 3)]
    assert {(o.step, o.page, o.status) for o in rep.outcomes} >= {("t_rs_step_b", 2, "skipped")}
    assert all(o.status in ("ok", "skipped") for o in rep.outcomes)
    # --json 报告汇总各步，不是最后一步那一次
    assert rep.steps == ["t_rs_step_a", "t_rs_step_b"] and rep.pages == [2, 3]
    st = eng.status(pages=[1, 2, 3])
    assert all(d["counts"]["stale"] == 0 for d in st["steps"].values())


def test_dry_run_and_page_filter(eng):
    eng.store.manifest("trs", "t_rs_step_a").invalidate(page_key(2), "x")
    p, rep = RS.run(eng, _steps(eng), dry_run=True, log=lambda s: None)
    assert rep is None and p.pages == [2] and CALLS == []
    p2 = RS.plan(eng, pages=[1, 3])
    assert not p2.by_step


def test_fmt_pages():
    assert RS._fmt_pages([1, 2, 3, 7, 9, 10]) == "1-3,7,9-10"
