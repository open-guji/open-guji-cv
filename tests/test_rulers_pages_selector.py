# -*- coding: utf-8 -*-
"""`console/routers/evals.py::_rulers_pages`：`/api/rulers` 的 `pages` 解析要认
`list:`/`cells:` 前缀，不能原样丢给 `Book.resolve_pages`。

O1 运维道报的坑：`api_rulers(pages="list:thin_chars_vol02")` 直接把整段字符串
交给 `resolve_pages`，那边当页码表达式解析、对 `int("list:thin_chars_vol02")`
抛 `ValueError`，console.log 反复出现 500。修法：`list:`/`cells:` 先按
`review/cards.py` 同一套约定换成页号，再交给 `resolve_pages`；查不到清单/清单
是空的，改抛 `BadRequest`（`@maps_http` 接得住，不是裸 500）。
"""
from __future__ import annotations

import pytest

from open_guji_cv.console.routers.evals import _rulers_pages
from open_guji_cv.errors import BadRequest

from helpers import make_book


def test_plain_selector_falls_through_to_resolve_pages():
    """普通选择子原样交给 `Book.resolve_pages`（`dev_set` 保序，不是本函数的活）。"""
    bk = make_book("b", dev_set=[3, 1, 2])
    assert _rulers_pages(bk, "dev_set") == [3, 1, 2]
    assert _rulers_pages(bk, "1-3") == [1, 2, 3]


def test_cells_prefix_resolves_to_pages():
    bk = make_book("b")
    assert _rulers_pages(bk, "cells:4:1:21,6:8:1") == [4, 6]


def test_list_prefix_resolves_to_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "thin_chars_vol02.txt").write_text(
        "# 注释行\nvol02:102:1:1\nvol02:106:4:2\n", encoding="utf-8")
    bk = make_book("vol02")
    assert _rulers_pages(bk, "list:thin_chars_vol02") == [102, 106]


def test_list_prefix_missing_file_raises_bad_request_not_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    bk = make_book("vol02")
    with pytest.raises(BadRequest):
        _rulers_pages(bk, "list:thin_chars_vol02")


def test_list_prefix_empty_file_raises_bad_request(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "empty.txt").write_text("# 只有注释\n", encoding="utf-8")
    bk = make_book("vol02")
    with pytest.raises(BadRequest):
        _rulers_pages(bk, "list:empty")
