# -*- coding: utf-8 -*-
"""`core/book.py::BookSpec.resolve_pages_ext`：`pages` 解析的公共入口。

issue #154（C #67 查出）：`resolve_pages` 不认 `list:`/`cells:` 前缀，直接把
整段字符串交给它解析会当页码表达式对 `int("list:...")`／`int("cells:...")`
抛 `ValueError`，在 `column_review`/`slot_count_review`/`step9`/`glyph_match`/
`products`/`runs` 六个 router 的八处调用里都能复现（`rulers`/`cutline` 此前
已各自修过，见 `console/routers/evals.py::_rulers_pages`、
`console/routers/cutline.py::_cutline_list_or_cells_ids`，两处逻辑与本文件
的判据一致，未改动、未合并——不在本卡写域，且两处对外异常语义不同：
`_rulers_pages` 缺清单文件时抛 `BadRequest`（400），`_cutline_list_or_cells_ids`
抛 `HTTPException(404)`）。

`resolve_pages_ext` 统一收口：`dev_set`/`all`/命名集/范围表达式原样交给
`resolve_pages`；`list:`/`cells:` 两种前缀先换成页号；任何一种写法解析不了
都收成 `BadRequest`（供 `@maps_http` 或调用方转 400），不再冒泡成 `ValueError`。
"""
from __future__ import annotations

import pytest

from open_guji_cv.errors import BadRequest

from helpers import make_book


def test_plain_selectors_fall_through_to_resolve_pages():
    """dev_set / all / 命名集 / 范围 / 显式列表——行为与 `resolve_pages` 完全一致。"""
    bk = make_book("b", dev_set=[3, 1, 2], sets={"jz": [7, 8]})
    assert bk.resolve_pages_ext("dev_set") == bk.resolve_pages("dev_set") == [3, 1, 2]
    assert bk.resolve_pages_ext(None) == bk.resolve_pages(None)
    assert bk.resolve_pages_ext("all") == bk.resolve_pages("all")
    assert bk.resolve_pages_ext("1-3") == [1, 2, 3]
    assert bk.resolve_pages_ext("3,1,2") == [1, 2, 3]
    assert bk.resolve_pages_ext("jz") == [7, 8]
    assert bk.resolve_pages_ext([5, 4]) == [4, 5]


def test_cells_prefix_resolves_to_pages():
    bk = make_book("b")
    assert bk.resolve_pages_ext("cells:4:1:21,6:8:1") == [4, 6]


def test_cells_prefix_with_explicit_book_id_kept_as_is():
    bk = make_book("vol01")
    assert bk.resolve_pages_ext("cells:bxgb:4:1:21") == [4]


def test_cells_prefix_bad_spec_raises_bad_request_not_value_error():
    bk = make_book("vol01")
    with pytest.raises(BadRequest):
        bk.resolve_pages_ext("cells:not-a-coordinate")


def test_list_prefix_resolves_to_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "thin_chars_vol02.txt").write_text(
        "# 注释行\nvol02:102:1:1\nvol02:106:4:2\n", encoding="utf-8")
    bk = make_book("vol02")
    assert bk.resolve_pages_ext("list:thin_chars_vol02") == [102, 106]


def test_list_prefix_missing_file_raises_bad_request_not_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    bk = make_book("vol02")
    with pytest.raises(BadRequest):
        bk.resolve_pages_ext("list:thin_chars_vol02")


def test_list_prefix_empty_file_raises_bad_request(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "empty.txt").write_text("# 只有注释\n", encoding="utf-8")
    bk = make_book("vol02")
    with pytest.raises(BadRequest):
        bk.resolve_pages_ext("list:empty")


def test_unrecognized_page_expression_raises_bad_request_not_value_error():
    """普通页码表达式写错（不是 list:/cells:，是纯粹语法错）也要收口成 `BadRequest`，
    这是 `resolve_pages` 本身（不认识的写法直接 `int()` 抛 `ValueError`）与
    `resolve_pages_ext` 的唯一行为差异——后者不让 `ValueError` 冒泡。"""
    bk = make_book("b")
    with pytest.raises(ValueError):
        bk.resolve_pages("not-a-page-expr")
    with pytest.raises(BadRequest):
        bk.resolve_pages_ext("not-a-page-expr")
