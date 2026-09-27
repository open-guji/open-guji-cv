# -*- coding: utf-8 -*-
"""5-b 真刻例多原型档「指纹按书」（转正二，2026-09-27）：钉住任务书判据——
「改前后对同一书，开关一变 `guji status` 就把 `rare_candidates` 及下游判为过期；
不开的书指纹不变」。

`guji status`（`core/engine.Engine.page_status`）判新鲜度用的就是
`self_hash(step, book, params) == manifest 里记的那份`，而 `self_hash` 里的
`params` 来自 `Engine.fingerprint()` 调的 `ctx.params_for(step)`。

背景：`RareCandidatesStep.spec.book_deps=("font",)` 早就把整本 `font` 字典的
文本摘进 `self_hash`（`core/engine._self_payload`）——单看「开关一变、
`self_hash` 就变」这条其实已经成立，不修 `params_hash` 本身也能过（细节见
`inbox/R-5b转正二/20260927-0426-cross.md`）。这里补的是设计一致性上的真缺口：
`params_hash` 里 `model_fingerprint` 字段本身此前仍是构造时的模块级默认，跟
产物体 `PageRare.model_fingerprint`（`run_page` 按书重算的那份）对不上；而且
`book_deps` 只兜得住「yaml 文本变了」，兜不住「`stores` 指的 `glyph_store`
目录内容自己长了（H 道新裁了真刻例）而 yaml 文本没动」。`_with_book_real_proto`
（`core/step.py`，跟已有的 `_with_book_corpus` 同一个模式）把这两个都收了：
`RunContext.params_for` 按 `ctx.book.font` 重算 `model_fingerprint` 并整份替换，
`run_page` 直接拿 `ctx.params_for(self)` 给的值写产物体，两边永远一致；
`real_proto_fingerprint` 本身是内容指纹（`instances/*.jsonl` 的 sha256，
2026-09-27 从 mtime 改过来，见 `test_fingerprint_content.py`），`glyph_store`
内容变化会跟着体现。

`core/step.py` 是 K 框架的写域（`进度/并行分工.md` §二表），这处改动经协调者在
cross 单回复里临时开窗授权（只许动 `params_for` 加 `_with_book_real_proto`），
不是 R 道日常写域。
"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401  （注册 STEPS）
from open_guji_cv.clustering.cnn_candidates import book_real_proto, full_fingerprint
from open_guji_cv.core.engine import self_hash
from open_guji_cv.core.step import STEPS, RunContext, _with_book_real_proto


def _book(font: dict):
    return SimpleNamespace(id="testbook", font=font, binarized_input=False)


def _ctx(font: dict) -> RunContext:
    return RunContext(_book(font), store=None, cache=None, log=lambda s: None)


# ── self_hash / guji status 判据 ───────────────────────────────────────

def test_self_hash_differs_when_real_proto_toggled_for_same_book():
    """任务书判据核心：同一本书，`font.real_proto.enabled` 一变，`self_hash`
    （`guji status` 判新鲜度那把尺子）要跟着变——`rare_candidates` 及以它为
    上游的下游都会被判过期（见 `core/engine.status` 的 DAG 过期传播）。"""
    step = STEPS["rare_candidates"]
    c_off, c_on = _ctx({"real_proto": {"enabled": False}}), _ctx({"real_proto": {"enabled": True}})
    h_off = self_hash(step, c_off.book, c_off.params_for(step))
    h_on = self_hash(step, c_on.book, c_on.params_for(step))
    assert h_off != h_on


def test_self_hash_differs_when_stores_change_for_same_book():
    """开着的前提下换 `stores`（比如四庫从只给自己库改成显式列别的库）也要变。"""
    step = STEPS["rare_candidates"]
    c_a = _ctx({"real_proto": {"enabled": True, "stores": ["output/glyph_store"]}})
    c_b = _ctx({"real_proto": {"enabled": True, "stores": ["output/glyph_store", "other"]}})
    h_a = self_hash(step, c_a.book, c_a.params_for(step))
    h_b = self_hash(step, c_b.book, c_b.params_for(step))
    assert h_a != h_b


def test_self_hash_matches_pre_change_baseline_for_disabled_book():
    """不开的书：`params_for()` 按书重算 `model_fingerprint`（本卡新加的那步）前后，
    `self_hash` 逐字节相同——不该白白让现有产物过期。拿「不经过 `params_for`、
    直接用构造时的模块级默认」（本卡改动前的行为）跟「经过 `params_for`」
    （改动后）比，书本身不变（`real_proto.enabled: false`）。"""
    step = STEPS["rare_candidates"]
    c = _ctx({"real_proto": {"enabled": False}})
    old_style_params = STEPS["rare_candidates"].spec.params()  # 未经 params_for，模块级默认
    h_before = self_hash(step, c.book, old_style_params)
    h_after = self_hash(step, c.book, c.params_for(step))
    assert h_before == h_after


# ── params_for / _with_book_real_proto 本身 ────────────────────────────

def test_params_for_uses_book_real_proto_when_enabled():
    c = _ctx({"real_proto": {"enabled": True}})
    p = c.params_for(STEPS["rare_candidates"])
    assert p.model_fingerprint == full_fingerprint(
        real_proto=book_real_proto({"real_proto": {"enabled": True}}))


def test_params_for_matches_module_default_when_disabled_or_missing():
    """不开的书（或压根没写这段——旧 yaml、十册四庫大多数曾经没加）指纹与模块级
    默认逐字节相同，这块新配置本身不该让任何现有产物过期。"""
    baseline = full_fingerprint()
    for font in ({}, {"real_proto": {"enabled": False}}):
        p = _ctx(font).params_for(STEPS["rare_candidates"])
        assert p.model_fingerprint == baseline, f"font={font!r} 时指纹不该偏离模块级默认"


def test_fingerprint_side_and_run_page_side_agree():
    """`params_for()`（引擎判指纹走这条）与再调一次 `_with_book_real_proto` 必须是
    同一个值（幂等）——`run_page` 现在直接用 `ctx.params_for(self)` 返回的
    `p.model_fingerprint` 写产物体，两边不会再分叉。"""
    c = _ctx({"real_proto": {"enabled": True, "stores": ["output/glyph_store"]}})
    a = c.params_for(STEPS["rare_candidates"])
    b = _with_book_real_proto(a, c)
    assert a.model_fingerprint == b.model_fingerprint


def test_explicit_model_fingerprint_is_not_overridden():
    """显式传了 `model_fingerprint` 的（如按某个历史指纹重放，同
    `GlyphMatchParams.db_fingerprint` 的先例）照用不误，不被这里覆盖。"""
    step = STEPS["rare_candidates"]
    c = _ctx({"real_proto": {"enabled": True}})
    c.params = {"rare_candidates": step.spec.params(model_fingerprint="pinned:value")}
    assert c.params_for(step).model_fingerprint == "pinned:value"


def test_book_without_font_attribute_treated_as_disabled():
    """`ctx.book` 没有 `font` 属性（旧结构 / 测试用的壳对象）按 `None` 处理，
    等价于关，不炸。"""
    c = RunContext(SimpleNamespace(id="testbook", binarized_input=False),
                   store=None, cache=None, log=lambda s: None)
    p = c.params_for(STEPS["rare_candidates"])
    assert p.model_fingerprint == full_fingerprint()


def test_steps_without_model_fingerprint_are_untouched():
    c = _ctx({"real_proto": {"enabled": True}})
    for sid in ("glyph_match", "row_segment", "seed_admit"):
        p = c.params_for(STEPS[sid])
        assert not hasattr(p, "model_fingerprint")
