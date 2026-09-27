# -*- coding: utf-8 -*-
"""`rare_panel.warm_font_index()` 的 K19 行为（任务书-K-控制台常驻内存，2026-09-28）：

1. 索引已经在磁盘上时正常预热（不动老行为）；
2. 缺盘 + 有活跑批时**推迟**，不建、`FONT_INDEX_STATE["deferred"]=True`；
3. 缺盘但没有活跑批时照常建。

不跑真规模——用 monkeypatch 控制 `all_ready`/`batch_active` 的返回值，
只验证决策分支对不对，跟 `font_candidates.warm()` 本身的建索引逻辑
（`tests/test_font_candidates.py`）分开测。
"""
from __future__ import annotations

import pytest

from open_guji_cv.clustering import font_candidates, rare_panel
from open_guji_cv.utils import batch_slice


@pytest.fixture(autouse=True)
def _reset_state():
    rare_panel.FONT_INDEX_STATE["deferred"] = False
    rare_panel.FONT_INDEX_STATE["ready"] = False
    yield
    rare_panel.FONT_INDEX_STATE["deferred"] = False
    rare_panel.FONT_INDEX_STATE["ready"] = False


def test_warm_font_index_defers_when_missing_and_batch_active(monkeypatch):
    calls = []
    monkeypatch.setattr(font_candidates, "all_ready", lambda cs, *a, **k: False)
    monkeypatch.setattr(font_candidates, "warm", lambda charsets, *a, **k: calls.append(charsets))
    monkeypatch.setattr(batch_slice, "batch_active", lambda *a, **k: True)

    rare_panel.warm_font_index()

    assert calls == [], "有活跑批时不该建索引"
    assert rare_panel.FONT_INDEX_STATE["deferred"] is True
    assert rare_panel.font_index_status() == {"deferred": True, "ready": False}


def test_warm_font_index_builds_when_missing_and_no_batch(monkeypatch):
    calls = []
    monkeypatch.setattr(font_candidates, "all_ready", lambda cs, *a, **k: False)
    monkeypatch.setattr(font_candidates, "warm", lambda charsets, *a, **k: calls.append(charsets))
    monkeypatch.setattr(batch_slice, "batch_active", lambda *a, **k: False)

    rare_panel.warm_font_index()

    assert len(calls) == 1, "没有跑批挡着，该照常建"
    assert rare_panel.FONT_INDEX_STATE == {"deferred": False, "ready": True}


def test_warm_font_index_builds_when_already_on_disk_even_if_batch_active(monkeypatch):
    """索引已经预建好（`guji cache build-font-index` 随发布带来的）时，
    有没有跑批不该影响——反正只是读盘，不占额外内存/CPU，不用避让。"""
    calls = []
    monkeypatch.setattr(font_candidates, "all_ready", lambda cs, *a, **k: True)
    monkeypatch.setattr(font_candidates, "warm", lambda charsets, *a, **k: calls.append(charsets))
    monkeypatch.setattr(batch_slice, "batch_active", lambda *a, **k: True)

    rare_panel.warm_font_index()

    assert len(calls) == 1
    assert rare_panel.FONT_INDEX_STATE["deferred"] is False


def test_font_index_status_returns_a_copy_not_the_live_dict():
    snap = rare_panel.font_index_status()
    snap["deferred"] = True
    assert rare_panel.FONT_INDEX_STATE["deferred"] is False, "改快照不能改到内部状态"


def test_warm_font_index_swallows_exceptions(monkeypatch):
    """建索引这段本来就是 `try/except Exception: pass`（后台线程崩了不能带崩
    控制台）——加了推迟判断之后这条老约束不能丢。"""
    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(font_candidates, "all_ready", _boom)
    rare_panel.warm_font_index()  # 不该抛
