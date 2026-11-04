# -*- coding: utf-8 -*-
"""终审取上下文：夹注双行读序、跨列、跨页、取字顺序（自造数据）。"""
from open_guji_cv.utils.final_ctx import BLANK, flatten, pick_char, window


def ch(i, slot, sub, char, admit=True):
    return {"id": i, "slot": slot, "sub": sub, "char": char, "admit": admit}


def test_jiazhu_reading_order_not_slot_order():
    # slot 1 正文；slot 2/3 是夹注双行：a 行 甲乙、b 行 丙丁。读序：甲乙丙丁，不是 甲丙乙丁
    col = {"col": 1, "chars": [ch("c1", 1, None, "正"), ch("c2a", 2, "a", "甲"), ch("c2b", 2, "b", "丙"),
                               ch("c3a", 3, "a", "乙"), ch("c3b", 3, "b", "丁"), ch("c4", 4, None, "末")]}
    s = flatten([(1, [col])])
    assert "".join(t for _, t in s) == "正甲乙丙丁末"
    assert window(s, "c4", 4) == ("甲乙丙丁", "")


def test_cross_column_and_page():
    p1 = [{"col": 2, "chars": [ch("b1", 1, None, "三"), ch("b2", 2, None, "四")]},
          {"col": 1, "chars": [ch("a1", 1, None, "一"), ch("a2", 2, None, "二")]}]
    p2 = [{"col": 1, "chars": [ch("n1", 1, None, "五")]}]
    s = flatten([(2, p2), (1, p1)])          # 页序乱给也按页号排
    assert "".join(t for _, t in s) == "一二三四五"
    assert window(s, "b2", 2) == ("二三", "五")      # 跨列、跨页
    assert window(s, "zzz") is None


def test_pick_char_order():
    c = {"id": "x", "char": "機", "admit": False}
    assert pick_char(c, {"align_char": "整"}) == "整"
    assert pick_char(c, None) == "機"
    assert pick_char({"id": "y"}, None) == BLANK
    assert pick_char({"id": "z", "char": "放", "admit": True}, {"align_char": "整"}) == "放"
