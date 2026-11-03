# -*- coding: utf-8 -*-
"""Step 参数四层的优先级（2026-11-03）：Step 默认 < 管线 yaml < 册配置 `params:` < 调用方覆盖。

以前册配置靠 `_with_book_params` 事后补「调用方没显式传的字段」，管线 yaml 写过的字段也算显式，
于是管线 yaml 反倒压过册配置（与 doc/design/册配置分层与运行覆盖.md 的顺序相反）。现在册配置在
`Engine.__init__` 里按字典叠在管线 yaml 之上。
"""
from __future__ import annotations

from dataclasses import replace

import open_guji_cv.steps  # noqa: F401
from helpers import make_book
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


def _eng(tmp_path, pl_params, book_params, caller=None):
    book = replace(make_book(), params=book_params)
    pl = Pipeline(id="t_prio", title="t", steps=["seed_admit"], params=pl_params)
    return Engine(book, pl, store=ProductStore(tmp_path / "p"), cache=ImageCache(tmp_path / "c"),
                  params=caller, log=lambda s: None)


def _p(eng):
    return eng.ctx.params_for(STEPS["seed_admit"])


def test_book_beats_pipeline(tmp_path):
    eng = _eng(tmp_path, {"seed_admit": {"use_context": False}}, {"seed_admit": {"use_context": True}})
    assert _p(eng).use_context is True


def test_pipeline_still_beats_step_default(tmp_path):
    eng = _eng(tmp_path, {"seed_admit": {"use_context": False}}, {})
    assert _p(eng).use_context is False


def test_caller_beats_book(tmp_path):
    eng = _eng(tmp_path, {"seed_admit": {"use_context": False}}, {"seed_admit": {"use_context": True}},
               caller={"seed_admit": {"use_context": False}})
    assert _p(eng).use_context is False


def test_book_null_drops_pipeline_value(tmp_path):
    default = STEPS["seed_admit"].spec.params().use_context
    eng = _eng(tmp_path, {"seed_admit": {"use_context": not default}}, {"seed_admit": {"use_context": None}})
    assert _p(eng).use_context is default


def test_unknown_step_in_book_params_is_ignored(tmp_path):
    eng = _eng(tmp_path, {}, {"no_such_step": {"x": 1}})
    assert "no_such_step" not in eng.ctx.params


def test_same_params_as_before_without_pipeline_params(tmp_path):
    """刻本链管线 yaml 没配 params：册配置叠法换了，参数指纹逐位不变。"""
    from open_guji_cv.core.engine import params_hash
    from helpers import make_ctx
    bp = {"seed_admit": {"use_context": False}}
    eng = _eng(tmp_path, {}, bp)
    old = make_ctx(tmp_path / "old", replace(make_book(), params=bp)).params_for(STEPS["seed_admit"])   # 旧路径：_with_book_params 事后补
    assert params_hash(_p(eng)) == params_hash(old)
