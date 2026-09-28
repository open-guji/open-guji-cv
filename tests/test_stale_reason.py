# -*- coding: utf-8 -*-
"""`guji status` 的过期原因（overview #174）：改了 yaml 的 `period_prior`（`book_deps`），
status 要说清「册配置 period_prior 180.0→204.0，须重跑」，而不只是报一个过期数；
`calibrate` 在先验漂了时要提示哪些步会过期。合成步骤、纯 tmp 数据，不碰真书。"""
from __future__ import annotations

import dataclasses

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401  —— 注册 raw_page 等产物种类

from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import FRESH, STALE, Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


class _Per(BaseModel):
    page: int
    period: float


class _P(BaseModel):
    gain: float = 1.0


if "t_sr_per" not in KINDS:
    register_kind(ProductKindSpec(id="t_sr_per", title="per", storage="numeric", unit="page", schema=_Per))
    register_kind(ProductKindSpec(id="t_sr_down", title="down", storage="numeric", unit="page", schema=_Per))

if "t_sr_gate" not in STEPS:
    @register_step
    class _Gate(Step):
        spec = StepSpec(id="t_sr_gate", title="合成闸2", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_sr_per",), params=_P,
                        book_deps=("period_prior",))

        def run_page(self, ctx, page):
            return {"t_sr_per": _Per(page=page, period=float(ctx.book.period_prior or 0))}

    @register_step
    class _Down(Step):
        spec = StepSpec(id="t_sr_down", title="下游", version="1", unit="page",
                        consumes=("t_sr_per",), produces=("t_sr_down",), params=_P)

        def run_page(self, ctx, page):
            return {"t_sr_down": ctx.product("t_sr_per", page)}


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in (1, 2):
        cv2.imwrite(str(raw / f"{pg}.png"), np.full((20, 20), 200, np.uint8))
    book = BookSpec(id="tsr", title="t", raw_dir=raw, dev_set=[1, 2], period_prior=180.0)
    pl = Pipeline(id="tsr", title="t", steps=["t_sr_gate", "t_sr_down"])
    pl.validate()
    return book, pl, ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")


def _eng(book, pl, store, cache, params=None):
    return Engine(book, pl, store=store, cache=cache, params=params, log=lambda s: None)


def test_manifest_records_book_dep_values(world):
    book, pl, store, cache = world
    _eng(book, pl, store, cache).run()
    assert store.manifest("tsr", "t_sr_gate").get("p0001").book == {"period_prior": 180.0}
    assert store.manifest("tsr", "t_sr_down").get("p0001").book is None   # 无 book_deps 的步不记


def test_status_names_changed_period_prior(world):
    book, pl, store, cache = world
    _eng(book, pl, store, cache).run()
    st = _eng(dataclasses.replace(book, period_prior=204.0), pl, store, cache).status()
    gate, down = st["steps"]["t_sr_gate"], st["steps"]["t_sr_down"]
    assert gate["counts"][STALE] == 2
    assert gate["pages"][1]["reason"] == "册配置 period_prior 180.0→204.0"
    assert gate["stale_reasons"] == {"册配置 period_prior 180.0→204.0": 2}
    assert down["stale_reasons"] == {"上游过期": 2}
    # 改回原值：又新鲜，没有过期原因
    st = _eng(book, pl, store, cache).status()
    assert st["steps"]["t_sr_gate"]["counts"][FRESH] == 2
    assert st["steps"]["t_sr_gate"]["stale_reasons"] == {}


def test_status_reason_params_and_old_entry(world):
    book, pl, store, cache = world
    _eng(book, pl, store, cache).run()
    st = _eng(book, pl, store, cache, params={"t_sr_gate": {"gain": 2.0}}).status()
    assert st["steps"]["t_sr_gate"]["stale_reasons"] == {"参数变了": 2}
    # 老条目（本改动之前跑的，没记 book）：分不出是代码还是册配置，要照实说
    m = store.manifest("tsr", "t_sr_gate")
    for k, e in m.all().items():
        m.put(dataclasses.replace(e, book=None))
    st = _eng(dataclasses.replace(book, period_prior=204.0), pl, store, cache).status()
    (reason,) = st["steps"]["t_sr_gate"]["stale_reasons"]
    assert reason.startswith("代码或册配置变了") and "period_prior" in reason


def test_status_cli_prints_reason(world, monkeypatch, capsys):
    from open_guji_cv import cli_v2
    book, pl, store, cache = world
    _eng(book, pl, store, cache).run()
    eng = _eng(dataclasses.replace(book, period_prior=204.0), pl, store, cache)
    monkeypatch.setattr(cli_v2, "_engine", lambda *a, **k: eng)
    cli_v2.cmd_status(type("A", (), {"book": "tsr", "pipeline": "tsr", "pages": "dev_set", "json": False})())
    out = capsys.readouterr().out
    assert "过期   2 页：册配置 period_prior 180.0→204.0，须重跑" in out
    assert "上游过期" in out


def test_calibrate_hint_names_column_gate():
    from open_guji_cv.utils.calibrate import Row, format_table
    diag = {"pages": 10, "body_pages": 10, "body_source": "t", "stale": 0, "checked": 10}
    txt = format_table([Row("period_prior", 180.0, 204.0)], diag, "b")
    assert "column_gate" in txt and "须重跑" in txt
    txt = format_table([Row("period_prior", 180.0, 181.0)], diag, "b")
    assert "须重跑" not in txt
