"""ids.py 单测：ID 生成/解析/阅读顺序排序。"""

import pytest

from open_guji_cv.clustering.ids import (CharId, make_id, parse_id,
                                         reading_order_key)


def test_make_and_parse_roundtrip():
    s = make_id("book1", "3", 2, 14)
    assert s == "book1:3:2:14"
    cid = parse_id(s)
    assert cid == CharId("book1", "3", 2, 14)
    assert str(cid) == s


def test_parse_split_page_stem():
    cid = parse_id("book2:1_right:3:0")
    assert cid.page == "1_right"
    assert cid.col == 3


def test_invalid_id_raises():
    with pytest.raises(ValueError):
        parse_id("book1:3:2")
    with pytest.raises(ValueError):
        make_id("bo:ok", "1", 1, 0)


def test_reading_order():
    """页升序 → 列升序（从右到左）→ 列内从上到下；右半页先于左半页。"""
    ids = [
        parse_id("b:2:1:0"),
        parse_id("b:1_left:1:0"),
        parse_id("b:1_right:2:5"),
        parse_id("b:1_right:1:3"),
        parse_id("b:1_right:1:0"),
        parse_id("b:10:1:0"),
    ]
    ordered = sorted(ids, key=reading_order_key)
    assert [str(i) for i in ordered] == [
        "b:1_right:1:0", "b:1_right:1:3", "b:1_right:2:5",
        "b:1_left:1:0", "b:2:1:0", "b:10:1:0",
    ]
