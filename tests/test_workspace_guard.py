# -*- coding: utf-8 -*-
"""跑批前必须显式声明库来源（`core/workspace.py::assert_workspace_declared`）。

2026-09-09 实锤：控制台在本机重启时漏带 `GUJI_WORKSPACE`，静默退回到仓内
那份几百条记录的示例库，vol02 101-150 页对着它跑了一遍——库匹配全给
`unsure`、上下文兜底救不回来、连 8-gram 锚定整理本都锚不上，而产物全程
`status: ok`，直到翻 `code_rev`/`params_hash` 才看出问题。根治：没声明
`GUJI_WORKSPACE`/`GUJI_GLYPH_DB`、又没显式放行时，跑批直接拒绝。
"""
from __future__ import annotations

import os

import pytest

from open_guji_cv.core.workspace import (assert_workspace_declared,
                                         using_sample_db)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """三个相关环境变量本测试内独立，不受运行环境影响、不泄漏出去。"""
    for k in ("GUJI_WORKSPACE", "GUJI_GLYPH_DB", "GUJI_ALLOW_SAMPLE_DB"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_using_sample_db_true_when_nothing_set():
    assert using_sample_db() is True


def test_using_sample_db_false_when_workspace_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    assert using_sample_db() is False


def test_using_sample_db_false_when_glyph_db_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GUJI_GLYPH_DB", str(tmp_path / "g.db"))
    assert using_sample_db() is False


def test_assert_raises_without_declaration():
    with pytest.raises(RuntimeError, match="没设 GUJI_WORKSPACE"):
        assert_workspace_declared()


def test_assert_passes_with_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    assert_workspace_declared()   # 不抛就是过


def test_assert_passes_with_explicit_allow(monkeypatch):
    monkeypatch.setenv("GUJI_ALLOW_SAMPLE_DB", "1")
    assert_workspace_declared()   # 显式放行，同样不抛
