# -*- coding: utf-8 -*-
"""T4 变体形模板「指纹按书」（2026-09-27）：`font.gw_variant.enabled` 决定 GlyphWiki
第六档模板开不开，跟 `font.real_proto`（5-b 转正二）同一套写法——`core/step.py`
`_with_book_gw()` 跟在 `_with_book_real_proto()` 之后叠一层，`RareCandidatesParams.
model_fingerprint` 按书重算并整份替换。

与 real_proto 那次的差异只有一点：GlyphWiki 目录（`cache/glyphwiki/catalog_64.npz`）
是引擎仓级的单一资源，不像 `glyph_store` 那样按书各指各的库，所以 `book_gw_variant`
只有一个 `enabled` 布尔，没有 `stores`。

`core/step.py` 是 K 框架的写域，本卡改动范围与 R-5b转正二那次相同（`params_for`
加一个 `_with_book_gw` 调用 + 新增该函数），沿用同一处授权先例。
"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401  （注册 STEPS）
from open_guji_cv.clustering.cnn_candidates import (
    book_gw_variant,
    book_real_proto,
    full_fingerprint,
)
from open_guji_cv.core.engine import self_hash
from open_guji_cv.core.step import STEPS, RunContext, _with_book_gw


def _book(font: dict):
    return SimpleNamespace(id="testbook", font=font, binarized_input=False)


def _ctx(font: dict) -> RunContext:
    return RunContext(_book(font), store=None, cache=None, log=lambda s: None)


# ── self_hash / guji status 判据 ───────────────────────────────────────

def test_self_hash_differs_when_gw_variant_toggled_for_same_book():
    """同一本书，`font.gw_variant.enabled` 一变，`self_hash` 要跟着变。"""
    step = STEPS["rare_candidates"]
    c_off = _ctx({"gw_variant": {"enabled": False}})
    c_on = _ctx({"gw_variant": {"enabled": True}})
    h_off = self_hash(step, c_off.book, c_off.params_for(step))
    h_on = self_hash(step, c_on.book, c_on.params_for(step))
    assert h_off != h_on


def test_self_hash_matches_pre_change_baseline_for_disabled_book():
    """不开的书：加了 `_with_book_gw` 这步前后 `self_hash` 逐字节相同。"""
    step = STEPS["rare_candidates"]
    c = _ctx({"gw_variant": {"enabled": False}})
    old_style_params = STEPS["rare_candidates"].spec.params()  # 未经 params_for，模块级默认
    h_before = self_hash(step, c.book, old_style_params)
    h_after = self_hash(step, c.book, c.params_for(step))
    assert h_before == h_after


# ── params_for / _with_book_gw 本身 ─────────────────────────────────────

def test_params_for_uses_book_gw_variant_when_enabled():
    c = _ctx({"gw_variant": {"enabled": True}})
    p = c.params_for(STEPS["rare_candidates"])
    assert p.model_fingerprint == full_fingerprint(gw_enabled=True)


def test_params_for_matches_module_default_when_disabled_or_missing():
    """不开的书（或没写这段）指纹与模块级默认逐字节相同——这块新配置本身不该让
    任何现有产物过期（即使本机 `cache/glyphwiki/catalog_64.npz` 真的存在）。"""
    baseline = full_fingerprint()
    for font in ({}, {"gw_variant": {"enabled": False}}):
        p = _ctx(font).params_for(STEPS["rare_candidates"])
        assert p.model_fingerprint == baseline, f"font={font!r} 时指纹不该偏离模块级默认"


def test_gw_and_real_proto_combine_independently(monkeypatch):
    """两个书级开关各自生效、互不打架——都开的书指纹既反映 real_proto 也反映 gw_variant，
    只开一个的书只反映那一个（回归 `_with_book_gw` 模块头「基准要带上 real_proto」
    那条：顺序若错，只开 real_proto 没开 gw_variant 的书会被误判成"已经算过"而
    跳过 gw 这一层，或反过来 gw 那一层把 real_proto 那一层的效果冲掉）。"""
    # GlyphWiki 目录不进仓（`cache/glyphwiki/`），缺席时 gw 开关按设计不影响指纹。
    # 这里把目录指纹钉成常量，测的是「开关叠加的接线」，不依赖本机有没有这份文件。
    import open_guji_cv.clustering.cnn_candidates as cc
    monkeypatch.setattr(cc, "gw_catalog_fingerprint",
                        lambda path=None, enabled=None: "gwstub" if (cc.GW_ENABLED if enabled is None else enabled) else "")
    font_both = {"real_proto": {"enabled": True}, "gw_variant": {"enabled": True}}
    font_real_only = {"real_proto": {"enabled": True}}
    font_gw_only = {"gw_variant": {"enabled": True}}

    p_both = _ctx(font_both).params_for(STEPS["rare_candidates"])
    p_real = _ctx(font_real_only).params_for(STEPS["rare_candidates"])
    p_gw = _ctx(font_gw_only).params_for(STEPS["rare_candidates"])
    p_none = _ctx({}).params_for(STEPS["rare_candidates"])

    assert p_both.model_fingerprint == full_fingerprint(
        real_proto=book_real_proto(font_both), gw_enabled=True)
    assert p_real.model_fingerprint == full_fingerprint(
        real_proto=book_real_proto(font_real_only), gw_enabled=False)
    assert p_gw.model_fingerprint == full_fingerprint(real_proto=book_real_proto(None), gw_enabled=True)
    # 四种组合两两不同（除非巧合碰撞，本地目录/checkpoint 都不同时应各自不同）
    fps = {p_both.model_fingerprint, p_real.model_fingerprint, p_gw.model_fingerprint,
           p_none.model_fingerprint}
    assert len(fps) == 4, f"四种开关组合的指纹应两两不同，实得 {fps}"


def test_fingerprint_side_and_run_page_side_agree():
    """`params_for()` 与再调一次 `_with_book_gw` 必须是同一个值（幂等）。"""
    c = _ctx({"gw_variant": {"enabled": True}})
    a = c.params_for(STEPS["rare_candidates"])
    b = _with_book_gw(a, c)
    assert a.model_fingerprint == b.model_fingerprint


def test_explicit_model_fingerprint_is_not_overridden():
    step = STEPS["rare_candidates"]
    c = _ctx({"gw_variant": {"enabled": True}})
    c.params = {"rare_candidates": step.spec.params(model_fingerprint="pinned:value")}
    assert c.params_for(step).model_fingerprint == "pinned:value"


def test_book_without_font_attribute_treated_as_disabled():
    c = RunContext(SimpleNamespace(id="testbook", binarized_input=False),
                   store=None, cache=None, log=lambda s: None)
    p = c.params_for(STEPS["rare_candidates"])
    assert p.model_fingerprint == full_fingerprint()


def test_book_gw_variant_defaults_false():
    assert book_gw_variant(None) is False
    assert book_gw_variant({}) is False
    assert book_gw_variant({"gw_variant": {}}) is False
    assert book_gw_variant({"gw_variant": {"enabled": False}}) is False
    assert book_gw_variant({"gw_variant": {"enabled": True}}) is True
