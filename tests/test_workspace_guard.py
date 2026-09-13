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


def test_sample_corpus_detected_by_size(monkeypatch, tmp_path):
    """语料也会静默退回仓内小样本——`using_sample_db` 那套只看路径来源，拦不住。

    2026-09-12 实锤（Step7 切分裁决）：`GUJI_WORKSPACE` 只写在 `~/.bashrc`，
    从 PowerShell / VS Code 起的控制台读不到，`corpus_path()` 退回仓内 17 KB
    样本 → vol02 全书 188 页 8-gram 锚定 186 页失败、`anchored` 为 0，而面板
    照常渲染，卡片上「整理本期望」两字全是噪声，全程无报错。

    判据必须看**文件大小**而不只是环境变量：`GUJI_WORKSPACE` 指对了但工作区
    语料没同步下来时，路径来源"正确"，读到的仍是小样本。
    """
    from open_guji_cv.core import workspace as W

    name = "zongmu_wenyuange_wikisource.txt"

    ws = tmp_path / "ws"
    (ws / "corpus").mkdir(parents=True)

    # 真语料（275 万字量级）→ 不是样本
    (ws / "corpus" / name).write_text("字" * 900_000, encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert W.using_sample_corpus(name) is False
    assert "⚠️" not in W.describe()["corpus"]

    # 工作区指对了、但语料没同步下来（只有 6000 字样本）→ 仍要报样本
    (ws / "corpus" / name).write_text("字" * 6_000, encoding="utf-8")
    assert W.using_sample_corpus(name) is True, "指对工作区但语料是小样本，也必须认出来"
    assert "⚠️" in W.describe()["corpus"]

    # 压根没有这个文件 → 按不可用处理，不能抛
    (ws / "corpus" / name).unlink()
    assert W.using_sample_corpus(name) is True

    # 没设 GUJI_WORKSPACE → 退回仓内样本
    monkeypatch.delenv("GUJI_WORKSPACE", raising=False)
    assert W.using_sample_corpus(name) is True
