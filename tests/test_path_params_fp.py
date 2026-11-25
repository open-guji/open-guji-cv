# -*- coding: utf-8 -*-
"""路径参数不进指纹（K238，2026-09-29）+ manifest 指纹迁移。

云端算好的整包导入服务器，`glyph_match.db_path` 留空时填的是本机绝对路径——进了
`params_hash` 就是全书判过期。合成步骤、纯 tmp 数据，不碰真书。"""
from __future__ import annotations

import dataclasses
import json

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401

from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import FRESH, STALE, Engine, params_hash
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


# ── 真步骤的登记 ─────────────────────────────────────────────────────
def test_registered_path_params_exist_and_leave_hash():
    expect = {
        "glyph_match": ("db_path",),
        "seed_admit": ("db_path", "variants", "note_lexicon", "exclusions", "shadow_model",
                       "group_flow_freq", "group_flow_tables", "group_flow_models", "group_flow_rr_shape", "group_flow_wu_shape", "group_flow_hou_shape", "group_flow_part_shape", "group_flow_pair_shape", "group_flow_pair_shapes", "group_flow_book_knn", "group_flow_near_knn", "stroke_veto", "pair_form", "lane_shape_first"),
        "context_decide": ("corpus", "general_corpus_dir", "ai_evidence", "llm_log_dir"),
        "align_ref": ("corpus",),
    }
    for sid, fields in expect.items():
        spec = STEPS[sid].spec
        assert spec.path_params == fields
        for f in fields:
            assert f in spec.params.model_fields, (sid, f)


def test_glyph_match_hash_ignores_db_path_but_not_other_params():
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    sp = STEPS["glyph_match"].spec
    a = GlyphMatchParams(db_path="/cloud/ws/glyph.db", db_fingerprint="x")
    b = GlyphMatchParams(db_path="/server/ws/glyph.db", db_fingerprint="x")
    h = lambda p: params_hash(p, sp.soft_params, sp.path_params)  # noqa: E731
    assert h(a) == h(b)
    assert params_hash(a, sp.soft_params) != params_hash(b, sp.soft_params)   # 老公式确实带路径
    assert h(a) != h(GlyphMatchParams(db_path="/cloud/ws/glyph.db", db_fingerprint="x", knn_k=3))


def test_corpus_path_out_but_corpus_content_in():
    from open_guji_cv.steps.context_decide import ContextDecideParams
    sp = STEPS["context_decide"].spec
    h = lambda p: params_hash(p, sp.soft_params, sp.path_params)  # noqa: E731
    a = ContextDecideParams(corpus="/a/x.txt", corpus_fingerprint="f1")
    b = ContextDecideParams(corpus="/b/x.txt", corpus_fingerprint="f1")
    c = ContextDecideParams(corpus="/a/x.txt", corpus_fingerprint="f2")
    assert h(a) == h(b) and h(a) != h(c)
    # 没有内容指纹的 `variants` 不许出指纹
    assert h(a) != h(ContextDecideParams(corpus="/a/x.txt", corpus_fingerprint="f1", variants="/v.json"))


def test_no_unregistered_path_like_defaults():
    """新增路径类参数必须表态：进 `path_params`（旁边有内容指纹）或写进例外并说明。
    扫每步参数默认值：绝对路径 / 带目录的相对路径 / 文件后缀的字符串 = 路径。"""
    allowed_in_hash: set[tuple[str, str]] = set()
    bad = []
    for sid, st in STEPS.items():
        if sid.startswith("t_"):          # 别的测试文件注册的合成步
            continue
        try:
            d = st.spec.params().model_dump(mode="json")
        except Exception:
            continue
        for k, v in d.items():
            if (isinstance(v, str) and ("/" in v or "\\" in v or v.endswith((".json", ".db", ".tsv", ".txt")))
                    and k not in st.spec.path_params and (sid, k) not in allowed_in_hash):
                bad.append((sid, k, v))
    assert not bad, f"路径类参数没登记 path_params：{bad}"


# ── 合成步骤：迁移 ────────────────────────────────────────────────────
class _Out(BaseModel):
    page: int
    v: float


class _P(BaseModel):
    gain: float = 1.0
    lib_path: str = "/cloud/lib.db"
    lib_fp: str = "L1"


if "t_fp_out" not in KINDS:
    register_kind(ProductKindSpec(id="t_fp_out", title="o", storage="numeric", unit="page", schema=_Out))
    register_kind(ProductKindSpec(id="t_fp_out2", title="o2", storage="numeric", unit="page", schema=_Out))


def _register(path_params):
    """同一个测试里换 `path_params` 要重登（登记表是进程级的）。"""
    STEPS.pop("t_fp_step", None)

    @register_step
    class _S(Step):
        spec = StepSpec(id="t_fp_step", title="路径步", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_fp_out",), params=_P,
                        path_params=path_params)

        def run_page(self, ctx, page):
            return {"t_fp_out": _Out(page=page, v=1.0)}


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in (1, 2):
        cv2.imwrite(str(raw / f"{pg}.png"), np.full((20, 20), 200, np.uint8))
    book = BookSpec(id="tfp", title="t", raw_dir=raw, dev_set=[1, 2])
    _register(())
    pl = Pipeline(id="tfp", title="t", steps=["t_fp_step"])
    pl.validate()
    return book, pl, ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")


def _eng(w, params=None):
    book, pl, store, cache = w
    return Engine(book, pl, store=store, cache=cache, params=params, log=lambda s: None)


def _old_world(w):
    """按老公式（路径在指纹里）跑一遍 → manifest 是「升级前」的样子。"""
    _register(())
    _eng(w, {"t_fp_step": {"lib_path": "/cloud/lib.db"}}).run()
    _register(("lib_path",))


def test_path_change_no_longer_stales(world):
    _register(("lib_path",))
    _eng(world, {"t_fp_step": {"lib_path": "/cloud/lib.db"}}).run()
    st = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}}).status()
    assert st["steps"]["t_fp_step"]["counts"][FRESH] == 2
    st = _eng(world, {"t_fp_step": {"lib_fp": "L2"}}).status()      # 内容指纹变了照样过期
    assert st["steps"]["t_fp_step"]["counts"][STALE] == 2


