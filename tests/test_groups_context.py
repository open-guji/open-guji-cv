"""M7 块 A4：前后各 20 字、遇段界即停。自造数据。"""
import pytest

from open_guji_cv.groups.context import WIDTH, as_window, ctx_key, flat_window, para_window


def test_mid_paragraph_full_window():
    p = "".join(chr(0x4E00 + i) for i in range(60))
    c = para_window([p], 0, 30)
    assert len(c.left) == WIDTH and len(c.right) == WIDTH
    assert c.left == p[10:30] and c.right == p[31:51]
    assert not c.cut_left and not c.cut_right


def test_stops_at_paragraph_start_and_end():
    p = "甲乙丙丁戊己庚辛壬癸"
    c = para_window([p], 0, 2)
    assert (c.left, c.cut_left) == ("甲乙", True)
    c = para_window([p], 0, 8)
    assert (c.right, c.cut_right) == ("癸", True)


def test_never_crosses_paragraphs():
    c = para_window(["前一段的字", "己已巳", "后一段的字"], 1, 0)
    assert c.left == "" and c.right == "已巳" and c.cut_left and c.cut_right


def test_exactly_full_window_is_not_cut():
    p = "a" * 20 + "X" + "b" * 20
    c = para_window([p], 0, 20)
    assert not c.cut_left and not c.cut_right


def test_flat_window_uses_paragraph_starts():
    chars = "一二三四五六七八九十"
    c = flat_window(chars, [0, 4, 7], 5)           # 段：一二三四 | 五六七 | 八九十；目标＝六
    assert (c.left, c.right) == ("五", "七")
    assert c.cut_left and c.cut_right


def test_out_of_range_and_window_adapter_and_key():
    with pytest.raises(IndexError):
        para_window(["ab"], 0, 2)
    w = as_window(para_window(["0123456789"], 0, 5))
    assert w(2) == ("34", "67") and w(0) == ("", "")
    assert ctx_key("左", "右").startswith("v2:")
