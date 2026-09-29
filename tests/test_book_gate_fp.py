"""书级开关门（`@book.<字段>`）+ 整体哈希步迁移 + real_proto 路径可移植（K#238c）。"""
from __future__ import annotations

import dataclasses

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import FRESH, STALE, Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products import fp_migrate
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.fp_migrate import migrate_book
from open_guji_cv.products.store import ProductStore


class _Out(BaseModel):
    page: int
    v: float


class _P(BaseModel):
    gain: float = 1.0


for _k in ("t_bg_opt", "t_bg_down"):
    if _k not in KINDS:
        register_kind(ProductKindSpec(id=_k, title=_k, storage="numeric", unit="page", schema=_Out))

READS: list[bool] = []


@register_step
class _Opt(Step):
    spec = StepSpec(id="t_bg_optstep", title="o", version="1", unit="page",
                    consumes=("raw_page",), produces=("t_bg_opt",), params=_P)

    def run_page(self, ctx, page):
        return {"t_bg_opt": _Out(page=page, v=float(ctx.book.ocr_candidates))}


@register_step
class _Down(Step):
    spec = StepSpec(id="t_bg_down", title="d", version="1", unit="page",
                    consumes=("raw_page",), optional_consumes=("t_bg_opt",),
                    optional_consumes_when=(("t_bg_opt", "@book.ocr_candidates"),),
                    produces=("t_bg_down",), params=_P)

    def run_page(self, ctx, page):
        got = ctx.book.ocr_candidates and ctx.has_product("t_bg_opt", page)
        READS.append(bool(got))
        return {"t_bg_down": _Out(page=page, v=1.0)}


def _world(tmp_path, ocr: bool):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    for pg in (1, 2):
        cv2.imwrite(str(raw / f"{pg}.png"), np.full((20, 20), 200, np.uint8))
    book = BookSpec(id="tbg", title="t", raw_dir=raw, dev_set=[1, 2], ocr_candidates=ocr)
    pl = Pipeline(id="tbg", title="t", steps=["t_bg_optstep", "t_bg_down"])
    pl.validate()
    return book, pl, ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")


def _eng(w, book=None):
    _, pl, store, cache = w
    return Engine(book or w[0], pl, store=store, cache=cache, log=lambda s: None)


def _fp(eng):
    return {p: eng.fingerprint(STEPS["t_bg_down"], p) for p in (1, 2)}


def test_gate_off_leftover_file_neither_read_nor_hashed(tmp_path):
    w = _world(tmp_path, ocr=False)
    _eng(w).run(steps=["t_bg_optstep"], )   # 点名跑：遗留旧产物在盘上
    eng = _eng(w)
    assert "t_bg_opt" not in eng.upstream_shas(STEPS["t_bg_down"], 1)
    fp_with = _fp(eng)
    # 遗留文件删掉，指纹不变
    import shutil
    shutil.rmtree(tmp_path / "products" / "tbg" / "t_bg_optstep")
    assert _fp(_eng(w)) == fp_with
    READS.clear()
    _eng(w).run(steps=["t_bg_down"])
    assert READS == [False, False]


def test_gate_on_behaves_as_before(tmp_path):
    w = _world(tmp_path, ocr=True)
    eng = _eng(w)
    eng.run()
    assert "t_bg_opt" in eng.upstream_shas(STEPS["t_bg_down"], 1)
    assert READS[-2:] == [True, True]
    assert _eng(w).status()["steps"]["t_bg_down"]["counts"][FRESH] == 2


def test_gate_off_upstream_change_does_not_stale(tmp_path):
    w = _world(tmp_path, ocr=False)
    _eng(w).run(steps=["t_bg_optstep"])
    _eng(w).run(steps=["t_bg_down"])
    # 遗留步的产物改掉（换成开关开时的值）
    ost = w[2].manifest("tbg", "t_bg_optstep")
    for k, e in list(ost.all().items()):
        ost.put(dataclasses.replace(e, sha256="f" * 64))
    st = _eng(w).status()["steps"]["t_bg_down"]["counts"]
    assert st[STALE] == 0 and st[FRESH] == 2


def test_migrate_after_wiring_explain_clean_and_no_false_fresh(tmp_path, monkeypatch):
    """整体哈希步 + 门：迁移只 --trust；真过期（上游变）不会被洗成新鲜。"""
    monkeypatch.setattr(fp_migrate, "WHOLE_HASH_STEPS", frozenset({"t_bg_down"}))
    w = _world(tmp_path, ocr=False)
    eng = _eng(w)
    eng.run()
    m = w[2].manifest("tbg", "t_bg_down")
    # 模拟「旧公式记录」：指纹被改成别的
    for k, e in list(m.all().items()):
        m.put(dataclasses.replace(e, fingerprint="0" * 24))
    assert _eng(w).status()["steps"]["t_bg_down"]["counts"][STALE] == 2
    r = migrate_book(_eng(w), [1, 2], steps=["t_bg_down"], apply=True)["t_bg_down"]
    assert r["migrated"] == 0 and "整体哈希步只能 --trust" in next(iter(r["skipped"]))
    r = migrate_book(_eng(w), [1, 2], steps=["t_bg_down"], trust=True, apply=True, explain=True)["t_bg_down"]
    assert r["migrated"] == 2 and not r["skipped"]
    assert _eng(w).status()["steps"]["t_bg_down"]["counts"][FRESH] == 2
    # 真过期：记录里的 upstream 与现算不同 → 不迁
    for k, e in list(m.all().items()):
        m.put(dataclasses.replace(e, fingerprint="1" * 24, upstream={"raw_page": "dead"}))
    r = migrate_book(_eng(w), [1, 2], steps=["t_bg_down"], trust=True, apply=True)["t_bg_down"]
    assert r["migrated"] == 0 and r["skipped"] == {"上游产物变了": 2}
    assert _eng(w).status()["steps"]["t_bg_down"]["counts"][STALE] == 2
    # 整体哈希步不接 --old-path
    assert "na" in migrate_book(_eng(w), [1, 2], old_paths={"t_bg_down": {"gain": "1"}},
                                trust=True)["t_bg_down"]


def test_real_proto_fingerprint_same_content_different_root(tmp_path, monkeypatch):
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.core import workspace

    def make(root):
        d = root / "output" / "glyph_store" / "instances"
        d.mkdir(parents=True)
        (d / "a.jsonl").write_text('{"x": 1}\n', encoding="utf-8")

    fps = []
    for name in ("cloud", "server"):
        root = tmp_path / name
        make(root)
        monkeypatch.setattr(workspace, "workspace_root", lambda r=root: r)
        en, specs = cc.book_real_proto({"real_proto": {"enabled": True}})
        assert specs[0].startswith(f"store:{root}")            # 传给下游的仍是绝对路径
        fps.append(cc.real_proto_fingerprint(specs, enabled=en))
    assert fps[0] and fps[0] == fps[1]
    # 内容变了照样变
    (tmp_path / "server" / "output" / "glyph_store" / "instances" / "a.jsonl").write_text("changed\n")
    assert cc.real_proto_fingerprint(specs, enabled=True) != fps[0]
