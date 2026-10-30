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
    assert SJ.parse_ref("　　翰林院編修今任監察御史<臣|>沈廷芳") == [11, 3]
    assert SJ.parse_ref("　　翰　　林　　院　　檢　　討<臣|>萬松齡") == [5, 3]
    assert SJ.parse_ref("總纂官<臣|>紀昀<臣|>陸錫熊<臣|>孫士毅") == [3, 2, 3, 3]   # 一列几位
    assert SJ.parse_ref("　　　監理") == [2]                                 # 整列普通字
    assert SJ.parse_ref("") == []                                            # 这一列不该有字
    assert SJ.parse_ref("（字位過密無法显示）<臣|>鄂爾泰") is None              # 整理本自己没录


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


def test_empty_ref_column_drops_everything():
    cols = [(_col(4, 3), (10.0, 170.0)) for _ in range(2)]
    out = SJ.segment_roster_page(cols, refs=["", None])          # 整理本说第一列空（印章、墨污）
    assert out[0].items == [] and "roster_ref_empty" in out[0].flags
    assert out[1].items                                           # None＝不知道，不动


def test_page_ref_lines_reads_daizhige_record_by_column(tmp_path):
    rec = {"id": "0243-0049", "geom": {"ncol": 8}, "cols": [
        {"no": 8, "runs": [{"t": "text", "start": 2, "s": "翰林院"},
                           {"t": "note", "start": 5, "r": [[0, "臣"]], "l": []},
                           {"t": "text", "start": 6, "s": "萬松齡"}]},
        {"no": 10, "runs": [{"t": "text", "start": 2, "s": "史記目錄"}]},
        {"no": 1, "runs": [{"t": "text", "start": 2, "s": "前半葉"}]}]}
    (tmp_path / "0243.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    pins = tmp_path / "p.jsonl"
    pins.write_text(json.dumps({"book": "01", "page": 47, "head": "0243-0049 243-12b h1"}) + "\n", encoding="utf-8")
    got = SJ.page_ref_lines(tmp_path, pins, "01", 47)
    assert got[1] == "翰林院<臣|>萬松齡" and got[3] == "史記目錄"
    assert got[2] == "" and len(got) == 8                          # 后半叶 8 列，空列给空串
    assert SJ.page_ref_lines(tmp_path, pins, "01", 48) is None


def test_three_chens_glued_to_neighbours():
    """一列三位（总纂官三人），每个小「臣」都和上下字粘成一块：靠「左半边没墨」认出三个臣。"""
    g = np.full((H, 180), 255, np.uint8)
    y = 100
    _stack(g, y, 3, 75)                        # 官衔 3 字，密排
    y += 2 * 75 + EM
    spans = []
    for n in (2, 3, 3):
        _stack(g, y - 8, 1, 0, x=110, size=50, stroke=5)     # 臣，上沿压进上一字
        g[y - 10:y + 2, 100:112] = 0                         # 和上一字粘一笔
        y += 50
        _stack(g, y, n, EM + 10)
        spans.append(n)
        y += n * (EM + 10)
    ink, _w = SJ.prepare(g, (10.0, 170.0))
    rc = SJ.segment_roster_column(ink, EM)
    assert SJ.refit_column(rc, ink, "總纂官<臣|>紀昀<臣|>陸錫熊<臣|>孫士毅", chen_row=None, em=EM)
    assert len(rc.items) == 3 + 2 + 3 + 3 + 3


def test_bottom_rule_stripped():
    """列底横框线（断成几截斜碎片）抹掉，末字框不往下拖到框线。"""
    g = np.full((H, 180), 255, np.uint8)
    _stack(g, 200, 3, EM + 30)
    g[1900:1903, 5:70] = 0
    g[1906:1909, 100:175] = 0
    ink, _w = SJ.prepare(g, (10.0, 170.0))
    out = SJ._strip_rules(ink)
    assert not out[1890:1920].any()
    assert out[200:700].any()


def test_header_cols():
    refs = {1: "欽定四庫全書", 2: "史記卷一百十一", 3: "漢太史令司馬遷撰", 4: "宋中郎外兵曹參軍裴駰集解",
            5: "唐國子博士𢎞文館學士司馬貞索隠", 6: "唐諸王侍讀率府長史張守節正義", 7: "衛將軍驃騎列傳第五十一",
            8: "集解裴駰曰凡是徐氏義稱徐姓名以别之餘者悉是駰註解并集衆家義"}
    assert SJ.header_cols(refs) == {1, 2, 3, 4, 5, 6, 7}
    assert SJ.header_cols({1: "總纂官<臣|>紀昀", 2: ""}) == set()
