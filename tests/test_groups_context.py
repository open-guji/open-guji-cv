"""M7 块 A4：前后各 20 字、不按段截断。自造数据。"""
import pytest

from open_guji_cv.groups.context import MISSING, WIDTH, as_window, ctx_key, window


def test_mid_text_full_window():
    p = "".join(chr(0x4E00 + i) for i in range(60))
    c = window(p, 30)
    assert len(c.left) == WIDTH and len(c.right) == WIDTH
    assert c.left == p[10:30] and c.right == p[31:51]
    assert not c.cut_left and not c.cut_right


def test_short_only_at_text_start_and_end():
    p = "甲乙丙丁戊己庚辛壬癸"
    c = window(p, 2)
    assert (c.left, c.cut_left) == ("甲乙", True)
    c = window(p, 8)
    assert (c.right, c.cut_right) == ("癸", True)


def test_does_not_stop_at_paragraph_boundaries():
    # 段界对窗口没有影响：连续字串里目标字短段两边照取满 20 字
    text = "前" * 30 + "己已巳" + "后" * 30
    c = window(text, 31)
    assert len(c.left) == WIDTH and len(c.right) == WIDTH
    assert c.left.endswith("己") and c.right.startswith("巳")


def test_exactly_full_window_is_not_cut():
    p = "a" * 20 + "X" + "b" * 20
    c = window(p, 20)
    assert not c.cut_left and not c.cut_right


def test_missing_placeholder_keeps_positions():
    c = window("甲" + MISSING + "乙丙", 2)
    assert c.left == "甲" + MISSING and c.right == "丙"


def test_out_of_range_and_window_adapter_and_key():
    with pytest.raises(IndexError):
        window("ab", 2)
    w = as_window(window("0123456789", 5))
    assert w(2) == ("34", "67") and w(0) == ("", "")
    assert ctx_key("左", "右").startswith("v3:")
