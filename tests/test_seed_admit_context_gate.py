# -*- coding: utf-8 -*-
"""Step7 context 通道的整理本互证（2026-09-20，bxgb 7 条误放行）。"""
from __future__ import annotations

from open_guji_cv.clustering.seeding import context_conflicts_ref
from open_guji_cv.clustering.variants import VariantMap


def _vm() -> VariantMap:
    return VariantMap.load(None)


def test_conflict_when_context_char_differs_from_ref():
    """p37c6s17：上下文定 四、整理本 疋 → 拦。"""
    assert context_conflicts_ref("四", "疋", _vm())


def test_no_conflict_when_same_semantic_variant():
    """匹/疋 是异体（同一语义代表字）→ 不拦；同字更不拦。"""
    vm = _vm()
    if vm.semantic("匹") == vm.semantic("疋"):
        assert not context_conflicts_ref("匹", "疋", vm)
    assert not context_conflicts_ref("多", "多", vm)


def test_no_ref_means_no_gate():
    """页没锚上 / 这格在 insert 段：没有对齐字就照旧走 margin 门槛。"""
    vm = _vm()
    assert not context_conflicts_ref("多", None, vm)
    assert not context_conflicts_ref("多", "", vm)
    assert not context_conflicts_ref(None, "皆", vm)
