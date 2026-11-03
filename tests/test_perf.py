"""跑批耗时统计 `core/perf.py`：span／count 的累加与空操作，引擎串行与并行都写出 perf 文件。"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401  —— 注册 raw_page 等产物种类
from open_guji_cv.core import perf
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


class PerfP(BaseModel):
    page: int


class NoParams(BaseModel):
    pass


if "t_perf" not in KINDS:
    register_kind(ProductKindSpec(id="t_perf", title="计时", storage="numeric", unit="page", schema=PerfP))

if "t_step_perf" not in STEPS:
    @register_step
    class StepPerfT(Step):
        spec = StepSpec(id="t_step_perf", title="合成计时步", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_perf",), params=NoParams,
                        parallel_safe=True)

        def run_page(self, ctx, page):
            with perf.span("外"), perf.span("内"):
                perf.count("格", 3)
            return {"t_perf": PerfP(page=page)}


def test_span_noop_outside_scope():
    with perf.span("x"):
        perf.count("y")
    assert perf._cur is None

    @perf.timed()
    def f(a):
        return a + 1
    assert f(1) == 2


def test_span_nested_and_accumulated():
    with perf.page_scope() as rec:
        for _ in range(2):
            with perf.span("a"), perf.span("b"):
                pass
        perf.count("hit")
        perf.count("hit", 2)
    d = rec.to_dict()
    assert d["spans"]["a"][0] == 2 and d["spans"]["a/b"][0] == 2
    assert d["counts"] == {"hit": 3}
    assert perf._cur is None


def test_disabled_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GUJI_PERF", "0")
    assert not perf.enabled()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("GUJI_PERF", raising=False)
    monkeypatch.delenv("GUJI_PERF_DIR", raising=False)
    raw = tmp_path / "raw"
    raw.mkdir()
    rng = np.random.default_rng(0)
    for pg in (1, 2, 3):
        cv2.imwrite(str(raw / f"{pg}.png"), rng.integers(0, 255, (20, 20), dtype=np.uint8))
    book = BookSpec(id="tperf", title="t", raw_dir=raw)
    pl = Pipeline(id="t_perf_pl", title="t", steps=["t_step_perf"])
    pl.validate()
    return book, pl, tmp_path


@pytest.mark.parametrize("jobs", [1, 2])
def test_engine_writes_perf_file(world, jobs):
    book, pl, tmp = world
    store = ProductStore(tmp / "products")
    eng = Engine(book, pl, store=store, cache=ImageCache(tmp / "cache"), log=lambda s: None)
    eng.run(pages=[1, 2, 3], jobs=jobs)
    files = list((tmp / "perf" / "tperf").glob("*.jsonl"))
    assert len(files) == 1, "产物根外的 perf/<册>/ 下一次运行一个文件"
    assert not (tmp / "products" / "perf").exists(), "不许写进产物根（会被打进产物包）"
    got = perf.load(files[0])
    assert got["run"]["book"] == "tperf" and got["run"]["machine"]["cpus"]
    assert got["end"] and got["end"]["stopped"] is False
    assert {p["page"] for p in got["pages"]} == {1, 2, 3}
    for p in got["pages"]:
        assert p["status"] == "ok" and p["spans"]["外/内"][0] == 1 and p["counts"]["格"] == 3
    (st,) = [s for s in got["steps"] if s["step"] == "t_step_perf"]
    assert st["ok"] == 3 and st["counts"]["格"] == 9 and len(st["slowest"]) == 3
    assert "check" in st["overhead"] and "land" in st["overhead"]

    # 再跑一遍：全是新鲜跳过，只计数、不写 page 行
    eng.run(pages=[1, 2, 3], jobs=jobs)
    files = sorted((tmp / "perf" / "tperf").glob("*.jsonl"))
    assert len(files) == 2
    got2 = [perf.load(f) for f in files]
    again = [g for g in got2 if g["run"]["run_id"] != got["run"]["run_id"]][0]
    assert again["pages"] == []
    (st2,) = again["steps"]
    assert st2["skipped"] == 3 and st2["ok"] == 0


def test_perf_does_not_change_products(world, monkeypatch):
    """开不开统计，产物与指纹逐位相同。"""
    book, pl, tmp = world
    out = {}
    for flag in ("1", "0"):
        monkeypatch.setenv("GUJI_PERF", flag)
        store = ProductStore(tmp / f"p{flag}" / "products")
        eng = Engine(book, pl, store=store, cache=ImageCache(tmp / f"p{flag}" / "cache"), log=lambda s: None)
        eng.run(pages=[1, 2, 3])
        mf = store.manifest(book.id, "t_step_perf")
        out[flag] = {pg: (mf.get(f"p{pg:04d}").fingerprint, mf.get(f"p{pg:04d}").sha256) for pg in (1, 2, 3)}
    assert out["1"] == out["0"]
    assert not (tmp / "p0" / "perf").exists()
