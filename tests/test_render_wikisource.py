# -*- coding: utf-8 -*-
"""9.1 md → 维基文库 wikitext（`render/wikisource.py`）：一列一行，版心出空行。"""
from open_guji_cv.render.wikisource import convert, convert_line


def test_one_line_per_column_blank_banxin_kept():
    md = "#第3页\n北行日錄上\n.........宋樓鑰撰\n\n乾道五年\n\n\n#第4页\n二十日壬寅\n"
    a, b = convert(md)
    assert a.wikitext == "<poem>\n北行日錄上\n" + "　" * 9 + "宋樓鑰撰\n\n乾道五年\n</poem>"   # 页末空列去掉
    assert b.wikitext == "<poem>\n二十日壬寅\n</poem>"


def test_fullwidth_space_kept():
    assert convert_line("..宋　樓") == "　　宋　樓"


def test_notes():
    assert convert_line("使會總管:jz[覿]{type=单行}副之") == "使會總管{{small|覿}}副之"
    assert convert_line("接晚過<案上|卷乾>") == "接晚過{{*|案上卷乾}}"
    assert convert_line("<似[[]]壁|係□處>") == "{{*|似□壁係□處}}"


def test_damaged_guess_and_gap():
    assert convert_line("累□{guess=塊}上") == "累塊上"
    assert convert_line("[[]]□") == "□□"
