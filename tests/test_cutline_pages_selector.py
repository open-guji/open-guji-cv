# -*- coding: utf-8 -*-
"""`console/routers/cutline.py::_cutline_list_or_cells_ids`：切线面板 `pages`
参数的 `list:`/`cells:` 前缀要能点名具体 id，不能替 `Book.resolve_pages` 掉坑。

`cells:` 此前没接，填 `cells:4:1:21` 会落到 `bk.resolve_pages(pages)`，当页码
表达式解析、对 `int("cells:4:1:21")` 抛 `ValueError`（D-Step6 道 09-27 报，见
overview inbox `D-Step6/20260927-1731-done-导回管线.md` 负结果 5，并入 #67）。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from open_guji_cv.console.routers.cutline import _cutline_list_or_cells_ids


def test_plain_selector_returns_none():
    assert _cutline_list_or_cells_ids("body", "vol01") is None
    assert _cutline_list_or_cells_ids("1-3", "vol01") is None


def test_cells_prefix_resolves_to_ids():
    assert _cutline_list_or_cells_ids("cells:4:1:21,6:8:1", "vol01") == {
        "vol01:4:1:21", "vol01:6:8:1"}


def test_cells_prefix_with_explicit_book_id_kept_as_is():
    assert _cutline_list_or_cells_ids("cells:bxgb:4:1:21", "vol01") == {"bxgb:4:1:21"}


def test_cells_prefix_bad_spec_raises_http_400_not_value_error():
    with pytest.raises(HTTPException) as exc_info:
        _cutline_list_or_cells_ids("cells:not-a-coordinate", "vol01")
    assert exc_info.value.status_code == 400


def test_list_prefix_resolves_to_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    (tmp_path / "lists").mkdir()
    (tmp_path / "lists" / "thin_chars_vol02.txt").write_text(
        "# 注释行\nvol02:102:1:1\nvol02:106:4:2\n", encoding="utf-8")
    assert _cutline_list_or_cells_ids("list:thin_chars_vol02", "vol02") == {
        "vol02:102:1:1", "vol02:106:4:2"}


def test_list_prefix_missing_file_raises_http_404_not_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as exc_info:
        _cutline_list_or_cells_ids("list:thin_chars_vol02", "vol02")
    assert exc_info.value.status_code == 404
