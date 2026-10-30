# -*- coding: utf-8 -*-
"""史記职名页按整理本字数重切（`books/shiji_wyg/roster_segment.refit_column` / `parse_ref` / `page_ref_lines`）。
合成数据，不读真书：密排官衔几何上并成大块，整理本说有 T 字，重切后要恰好 T 字。"""

from __future__ import annotations

import json

import numpy as np

from open_guji_cv.books.shiji_wyg import roster_segment as SJ

H = 2400
EM = 110


def _stack(img, y0, n, pitch, *, x=35, size=EM, stroke=7):
    """从 y0 起竖排 n 个笔画字，字距 pitch（pitch < size 时彼此相粘）。"""
    for i in range(n):
        y = y0 + i * pitch
        img[y:y + size, x:x + stroke] = 0
        img[y:y + size, x + size - stroke:x + size] = 0
        for t in (0, size // 2, size - stroke):
            img[y + t:y + t + stroke, x:x + size] = 0


def _col(n_title, n_name, *, title_pitch=70):
    """官衔 n_title 个密排字 + 偏右小「臣」+ n_name 个人名字。白底 255，墨 0。"""
    g = np.full((H, 180), 255, np.uint8)
    _stack(g, 150, n_title, title_pitch)
    y_chen = 150 + (n_title - 1) * title_pitch + EM + 40
    _stack(g, y_chen, 1, 0, x=110, size=50, stroke=5)
    _stack(g, y_chen + 90, n_name, EM + 40)
    return g


def _run(n_title, n_name, ref):
    g = _col(n_title, n_name)
    ink, _w = SJ.prepare(g, (10.0, 170.0))
    rc = SJ.segment_roster_column(ink, EM)
    got = SJ.refit_column(rc, ink, ref, chen_row=None, em=EM)
    return rc, got


def test_parse_ref():
    assert SJ.parse_ref("　　翰林院編修今任監察御史<臣|>沈廷芳") == (11, 3)
    assert SJ.parse_ref("　　翰　　林　　院　　檢　　討<臣|>萬松齡") == (5, 3)
    assert SJ.parse_ref("　　　監理") == (2, -1)                       # 整列普通字
    assert SJ.parse_ref("　（字位過密　無法显示）　<臣|>鄂爾泰") is None   # 整理本自己缺字
    assert SJ.parse_ref("和碩和親王<臣|>𢎞晝等上言<臣|>等奉") is None     # 正文进表页，不是职名列


def test_dense_title_is_recut_to_ref_count():
    rc, got = _run(9, 3, "翰林院編修今任監察<臣|>沈廷芳")
    assert got and len(rc.items) == 9 + 1 + 3
    assert "roster_ref_refit" in rc.flags
    ys = [it.y0 for it in rc.items]
    assert ys == sorted(ys)                               # 读序自上而下
    assert all(b.y0 >= a.y1 - 10 for a, b in zip(rc.items[:8], rc.items[1:9]))   # 重切后字框基本不叠


def test_correct_column_is_left_alone():
    g = _col(4, 3, title_pitch=190)                       # 匀开：几何本来就数对
    ink, _w = SJ.prepare(g, (10.0, 170.0))
    rc = SJ.segment_roster_column(ink, EM)
    before = [(it.y0, it.y1) for it in rc.items]
    assert len(before) == 8
    assert not SJ.refit_column(rc, ink, "甲乙丙丁<臣|>戊己庚")
    assert [(it.y0, it.y1) for it in rc.items] == before


def test_plain_column_without_chen_is_split_to_ref_count():
    g = np.full((H, 180), 255, np.uint8)
    _stack(g, 200, 5, 60)                                  # 5 个字相粘成一大块
    ink, _w = SJ.prepare(g, (10.0, 170.0))
    rc = SJ.segment_roster_column(ink, EM)
    assert SJ.refit_column(rc, ink, "　　一二三四五")
    assert len(rc.items) == 5


def test_page_with_other_column_count_than_ref_is_untouched():
    cols = [(_col(9, 3), (10.0, 170.0)) for _ in range(3)]
    plain = SJ.segment_roster_page(cols)
    out = SJ.segment_roster_page(cols, refs=["甲乙<臣|>丙"])      # 1 行 ≠ 3 列
    assert [len(c.items) for c in out] == [len(c.items) for c in plain]


def test_page_ref_lines_reads_pins_and_block(tmp_path):
    corpus = tmp_path / "c.txt"
    corpus.write_text("#@ H1\n甲乙<臣|>丙\n\n丁戊<臣|>己\n#@ H2\n庚\n", encoding="utf-8")
    pins = tmp_path / "p.jsonl"
    pins.write_text(json.dumps({"book": "01", "page": 7, "head": "H1"}) + "\n", encoding="utf-8")
    assert SJ.page_ref_lines(corpus, pins, "01", 7) == ["甲乙<臣|>丙", "丁戊<臣|>己"]
    assert SJ.page_ref_lines(corpus, pins, "01", 8) is None
