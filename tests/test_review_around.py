# -*- coding: utf-8 -*-
"""跨列/跨页拼上下文（`console/routers/review.py::_around`）。

用户 2026-09-09：「文字在第一个或最后一个字时看不到上下文，应该动态加载前
十后十，不论是否在一行。」列内/页内都够不着 N 个字时，要跨到前一列/前一页
最后一列、后一列/后一页第一列——col 右→左递增、页内到头了才翻页。

用假 `ProductStore`（不需要真工作区）造两页 × 两列 × 三字的最小语料，
盖住三种拼接：列内够、跨列不跨页、跨页。
"""
from __future__ import annotations

from open_guji_cv.console.routers.review import _around, _column_slots
from open_guji_cv.products.kinds.recog import (ColumnDecision, DecisionRec,
                                               PageDecision)


class FakeStore:
    """只认 `context_decide`/`context_decision`；够 `_column_slots` 用了——
    它 `m is None and d is None` 才算空页，其余三路（glyph_match/ocr/admit_decide）
    留 None 也不影响拼字符串本身。"""

    def __init__(self, pages: dict[int, PageDecision]):
        self.pages = pages

    def read(self, book, step_id, key, kind_id):
        if kind_id != "context_decision":
            return None
        pg = int(key.replace("p", "")) if key.startswith("p") else int(key)
        return self.pages.get(pg)


def _page(page: int, cols: dict[int, str]) -> PageDecision:
    """`cols`： {列号: 这一列的字符串}，一字一格，slot 从 1。"""
    columns = []
    for col, text in cols.items():
        chars = [DecisionRec(id=f"b:{page}:{col}:{i+1}", slot=i + 1, char=ch)
                 for i, ch in enumerate(text)]
        columns.append(ColumnDecision(col=col, chars=chars))
    return PageDecision(page=page, columns=columns)


def _mk_store():
    # 页 1：col1「甲乙丙」col2「丁戊己」；页 2：col1「庚辛壬」
    # 阅读序（col 右→左，页内 col 到头翻页）：甲乙丙丁戊己庚辛壬
    return FakeStore({
        1: _page(1, {1: "甲乙丙", 2: "丁戊己"}),
        2: _page(2, {1: "庚辛壬"}),
    })


def test_column_slots_reads_one_column():
    st = _mk_store()
    out = _column_slots(st, "b", 1, 2, {})
    assert "".join(x["char"] for x in out) == "丁戊己"


def test_around_within_column_no_cross_needed():
    st = _mk_store()
    r = _around(st, "b", 1, 1, 2, before=1, after=1, cache={})
    # 本位「乙」（col1 slot2），前后各 1 个都在同一列里
    assert r["text"] == "甲乙丙"
    assert r["text"][r["at"]] == "乙"


def test_around_crosses_column_same_page():
    st = _mk_store()
    # 本位 col1 的「丙」（列尾），往后要跨到 col2 取「丁」
    r = _around(st, "b", 1, 1, 3, before=2, after=2, cache={})
    assert r["text"] == "甲乙丙丁戊"
    assert r["text"][r["at"]] == "丙"


def test_around_crosses_page_boundary():
    st = _mk_store()
    # 本位页 1 col2 的「己」（全页最后一格）：col2 = 丁戊己，本列内往前已经
    # 够 before=2（丁戊），只有往后要翻到页 2 col1 取「庚辛」
    r = _around(st, "b", 1, 2, 3, before=2, after=2, cache={})
    assert r["text"] == "丁戊己庚辛"
    assert r["text"][r["at"]] == "己"
    # 往前跨列同页：页 2 col1「庚」（列头/页头），往前翻回页 1 col2 最后两格
    r2 = _around(st, "b", 2, 1, 1, before=2, after=2, cache={})
    assert r2["text"] == "戊己庚辛壬"
    assert r2["text"][r2["at"]] == "庚"


def test_around_clamps_at_book_start():
    st = _mk_store()
    # 页 1 col1 的「甲」是全书第一格，往前无处可跨，前面就是没有
    r = _around(st, "b", 1, 1, 1, before=5, after=1, cache={})
    assert r["text"] == "甲乙"
    assert r["at"] == 0
