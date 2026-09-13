# -*- coding: utf-8 -*-
"""边框类裁决卡片（Step1/2 标注、含"页级抬头标注"）必须读预清理后的图，
不能悄悄用原图——同 `render/overlay.py::overlay` 2026-09-12 修过的那个坑：
登记过 preclean 且产物已生成的页，管线实际处理的是修好的那张，标注卡片
看的却是原图，会出现"卡片上反色带还在、实跑却是好的"这种两边对不上的
假象（用户反馈：Step3 页级抬头标注用的是原图）。

`review/border_cards.py::_read_gray` 是 cols/head/headcol/outer/colborder
五种卡片共用的读图函数，钉死它走 `effective_raw_path` 就覆盖了全部五种。
"""

from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.review import border_cards


def test_read_gray_uses_effective_raw_path(tmp_path, monkeypatch):
    """_read_gray 必须调用 effective_raw_path，不能直接读 book.raw_path——
    用一张假的"已清理"图占住 effective_raw_path 的返回值，断言 _read_gray
    读到的正是这张图，而不是 book.raw_path 指向的另一张。"""
    raw_path = tmp_path / "raw.png"
    cleaned_path = tmp_path / "cleaned.png"
    import cv2
    cv2.imwrite(str(raw_path), np.full((10, 10), 0, dtype=np.uint8))       # 全黑：假装是"脏"原图
    cv2.imwrite(str(cleaned_path), np.full((10, 10), 255, dtype=np.uint8))  # 全白：假装是修好的图

    class FakeBook:
        id = "fakebook"
        preclean = {1: [{"kind": "inverted_band"}]}

        def raw_path(self, page):
            return raw_path

    monkeypatch.setattr(border_cards, "load_book", lambda book_id: FakeBook())
    monkeypatch.setattr(border_cards, "effective_raw_path", lambda book, page, **kw: cleaned_path)

    gray = border_cards._read_gray("fakebook", 1)
    assert gray.mean() > 200, "_read_gray 应该读到 effective_raw_path 返回的（清理后的）图，不是原图"


def test_read_gray_falls_back_to_raw_when_not_precleaned(tmp_path, monkeypatch):
    """没登记 preclean 的页，effective_raw_path 本身会退回原图——
    这里验证 _read_gray 老实转发它的返回值，不做自己的判断。"""
    raw_path = tmp_path / "raw.png"
    import cv2
    cv2.imwrite(str(raw_path), np.full((10, 10), 128, dtype=np.uint8))

    class FakeBook:
        id = "fakebook"
        preclean = {}

        def raw_path(self, page):
            return raw_path

    monkeypatch.setattr(border_cards, "load_book", lambda book_id: FakeBook())
    monkeypatch.setattr(border_cards, "effective_raw_path", lambda book, page, **kw: raw_path)

    gray = border_cards._read_gray("fakebook", 1)
    assert gray is not None
    assert gray.shape == (10, 10)
