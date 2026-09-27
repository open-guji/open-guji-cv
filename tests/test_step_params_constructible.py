# -*- coding: utf-8 -*-
"""每个 Step 的参数类都要**构造得出来**（2026-09-21）。

起因：`RareCandidatesParams` 用了 `self.struct_probe` 三处，类里却没声明这个字段，
`RareCandidatesParams()` 直接抛 `AttributeError`，Step5-b 对谁都起不来。
pydantic 的 `model_post_init` 在校验之后跑，所以这种错**只在构造实例时炸**——
`import` 阶段、语法检查、`grep` 全都看不出来，跑批才死。

引擎每判一次新鲜度就 `step.spec.params()` 一次（`RunContext.params_for`），
所以「缺省参数构造不出来」等于这一步整个不可用。这条测试很便宜，值得替所有步钉住。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401  （注册 STEPS）
from open_guji_cv.core.step import STEPS


@pytest.mark.parametrize("sid", sorted(STEPS))
def test_default_params_construct(sid):
    step = STEPS[sid]
    p = step.spec.params()          # `spec.params` 是参数类本身
    # `model_post_init` 里填的派生字段（库/语料/模型指纹）也要真的填上了
    for f in ("db_fingerprint", "corpus_fingerprint", "model_fingerprint", "judge_fingerprint"):
        if hasattr(p, f):
            assert isinstance(getattr(p, f), str), f"{sid}.{f} 不是字符串"


@pytest.mark.parametrize("sid", sorted(STEPS))
def test_params_roundtrip_through_dump(sid):
    """`model_dump()` → 重新构造：`_with_book_corpus` 等处就是这么换字段的。"""
    step = STEPS[sid]
    p = step.spec.params()
    again = type(p)(**p.model_dump())
    assert type(again) is type(p)
