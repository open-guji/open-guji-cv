# -*- coding: utf-8 -*-
"""Step5-d 按坐标对位（`align: coord`，overview#195）。

用户 09-28：vol03 p3 一方大印章压住半页，认字全烂、整页锚不上。四庫整理本逐行＝刻本一列，
格数对得上就按位置配字。这里钉住：列内几何配位（含印章切出来的假格）、夹注 a/b、
几何对不上/有歧义就退回、与现役对位打架整列退回、端到端 `align_ref` 产物不动现役 `chars`。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, write_product
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.recog import AlignRec, ColumnMatch, MatchRec, PageMatch
from open_guji_cv.steps import align_ref_coord as C
from open_guji_cv.steps.align_ref import AlignRefParams, AlignRefStep, _coord_conflict

BOOK, PAGE = "tbook", 1


# ── 行表解析 ────────────────────────────────────────────────────────────
def test_parse_lines_splits_note_into_a_b_rows():
    """`讀易私言一卷<兩江總督採進本>`：夹注 7 字 → 右行 4（兩江總督）、左行 3（採進本）。"""
    (ln,) = C.parse_lines("讀易私言一卷<兩江總督採進本>")
    assert "".join(u.a for u in ln.units if u.kind == "c") == "讀易私言一卷"
    notes = [(u.a, u.b) for u in ln.units if u.kind == "n"]
    assert notes == [("兩", "採"), ("江", "進"), ("總", "本"), ("督", "")]
    assert ln.n == 10


def test_parse_lines_drops_punct_and_blank_lines_and_counts_han_offsets():
    lines = C.parse_lines("甲乙，丙\n\n丁戊。\n")
    assert [ln.text for ln in lines] == ["甲乙丙", "丁戊"]
    assert [ln.han_start for ln in lines] == [0, 3]


def test_parse_lines_note_across_lines():
    """夹注跨列：`<` 在上一行开、`>` 在下一行关，两行各自切 a/b。"""
    a, b = C.parse_lines("正文<甲乙丙\n丁戊>尾")
    assert [(u.a, u.b) for u in a.units if u.kind == "n"] == [("甲", "丙"), ("乙", "")]
    assert [(u.a, u.b) for u in b.units if u.kind == "n"] == [("丁", "戊")]
    assert b.units[-1] == C.Unit("c", "尾")


# ── 列内配位 ────────────────────────────────────────────────────────────
def _cu(slot, g, ch="", kind="c"):
    if kind == "c":
        return C.CellUnit("c", slot, g, {"": f"id{slot}"}, {"": ch})
    return C.CellUnit("n", slot, g, {"a": f"id{slot}a", "b": f"id{slot}b"},
                      {"a": ch[:1], "b": ch[1:2]})


def test_exact_column_maps_by_position_without_recognition():
    """格数＝字数、几何逐格递增：认字全错也按位置配上（不依赖图像认字）。"""
    (ln,) = C.parse_lines("元許衡撰")
    units = [_cu(s, s + 2.0, "某") for s in range(1, 5)]   # 行首缩进 2 格
    r = C.coord_column(units, ln)
    assert r.ok and [t[3] for t in r.recs] == list("元許衡撰")


def test_seal_noise_cells_outside_text_get_blank():
    """p3 列5 型：行首两格是印章切出来的假格（整理本空格位），字身只认对两三个。"""
    (ln,) = C.parse_lines("元許衡撰衡字")
    units = [_cu(1, 1.0, "海"), _cu(2, 2.0, "中")]
    units += [_cu(3 + i, 3.0 + i, ch) for i, ch in enumerate("元詩衡撰衡某")]
    units += [_cu(9, 9.1, "籠"), _cu(10, 10.0, "事")]
    r = C.coord_column(units, ln)
    assert r.ok
    got = {t[0]: t[3] for t in r.recs}
    assert got["id1"] == got["id2"] == got["id9"] == got["id10"] == ""
    assert "".join(got[f"id{s}"] for s in range(3, 9)) == "元許衡撰衡字"


def test_jiazhu_rows_map_a_and_b():
    (ln,) = C.parse_lines("讀易<兩江總督採進本>")
    units = [_cu(1, 1.0, "讀"), _cu(2, 2.0, "易")]
    units += [_cu(3 + i, 3.0 + i, "", kind="n") for i in range(4)]
    r = C.coord_column(units, ln)
    assert r.ok
    got = {t[0]: t[3] for t in r.recs}
    assert [got[f"id{s}a"] for s in range(3, 7)] == list("兩江總督")
    assert [got[f"id{s}b"] for s in range(3, 7)] == ["採", "進", "本", ""]


def test_fallback_when_extra_cell_falls_inside_text_span():
    """多出来的格落在文字范围里（切多了一格）——不是假格，是格数对不上，退回。"""
    (ln,) = C.parse_lines("元許衡撰")
    units = [_cu(1, 1.0), _cu(2, 1.5), _cu(3, 2.0), _cu(4, 3.0), _cu(5, 4.0)]
    assert not C.coord_column(units, ln).ok


def test_fallback_when_fewer_cells_or_kind_mismatch():
    (ln,) = C.parse_lines("元許衡撰")
    assert not C.coord_column([_cu(s, float(s)) for s in range(1, 4)], ln).ok
    (ln2,) = C.parse_lines("元許<衡撰>")
    assert not C.coord_column([_cu(s, float(s)) for s in range(1, 4)], ln2).ok


def test_ambiguous_placements_fall_back():
    """两个假格一前一后、载体一个字都不吻合：两种配法几何上都成立，分不出 → 退回。"""
    (ln,) = C.parse_lines("元許衡")
    units = [_cu(1, 1.0, "某"), _cu(2, 2.0, "某"), _cu(3, 3.0, "某"), _cu(4, 4.0, "某")]
    r = C.coord_column(units, ln)
    assert not r.ok and "歧义" in r.note


def test_conflict_with_legacy_equal_rejects_column():
    """vol03 全册 83 格不一致全是「光盘版分行错一位」：现役 `equal` 位说的字不同就整列退回。"""
    legacy = {"x1": AlignRec(id="x1", col=1, slot=1, align_char="元", align_op="equal")}
    assert _coord_conflict([("x1", 1, None, "王", 1.0)], legacy, {})
    replace = {"x1": AlignRec(id="x1", col=1, slot=1, align_char="元", align_op="replace")}
    assert not _coord_conflict([("x1", 1, None, "王", 1.0)], replace, {})
    assert _coord_conflict([("x2", 2, None, "", 2.0)], {}, {"x2": "據"})


# ── 端到端：align_ref 产物 ───────────────────────────────────────────────
def _uniq_lines(n: int, width: int = 19) -> list[str]:
    base = 0x4E00
    return ["".join(chr(base + i * width + k) for k in range(width)) for i in range(n)]


def _setup(tmp_path, monkeypatch, *, seal_col_carrier_wrong: bool = True):
    lines = _uniq_lines(40)
    corpus = tmp_path / "ref.txt"
    corpus.write_text("\n".join(lines), encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    page_lines = lines[20:23]
    cols_m, cols_c = [], []
    for ci, text in enumerate(page_lines, start=1):
        mrecs, crecs = [], []
        slots = list(range(1, 20))
        if ci == 1:
            slots = list(range(1, 22))      # 前两格印章假格：slot 1、2 空，字从 slot 3 起
        for i, slot in enumerate(slots):
            if ci == 1 and slot <= 2:
                ch = "㐀"                                   # 假格上认出来的噪声
            else:
                k = slot - 3 if ci == 1 else slot - 1
                ch = text[k]
                if ci == 1 and seal_col_carrier_wrong and k % 3:
                    ch = "㐁"                               # 印章压着，三个里认错两个
            mrecs.append(MatchRec(id=f"{BOOK}:{PAGE}:{ci}:{slot}", slot=slot, verdict="unsure",
                                  cov=0.9, candidates=[(ch, 0.9)]))
            g = float(slot) if ci == 1 else float(slot) + 2   # 列2、3 也缩进 2 格
            crecs.append(CellRec(slot=slot, pos=slot, y0=(g - 1) * 100, y1=g * 100, x0=0, x1=100,
                                 kind="char", order=i))
        cols_m.append(ColumnMatch(col=ci, ok=True, chars=mrecs))
        cols_c.append(ColumnCells(col=ci, ok=True, n_body_slots=21, period=100.0,
                                  border_top=0.0, cells=crecs))
    write_product(ctx, "glyph_match", PAGE, glyph_match=PageMatch(page=PAGE, columns=cols_m))
    write_product(ctx, "row_segment", PAGE,
                  cells=PageCells(page=PAGE, period=100.0, ref_w=100.0, columns=cols_c))
    return ctx, str(corpus), page_lines


def _with_params(ctx, corpus, coord):
    from open_guji_cv.core.step import RunContext
    return RunContext(ctx.book, ctx.store, ctx.cache,
                      params={"align_ref": AlignRefParams(corpus=corpus, coord=coord)},
                      log=lambda s: None)


def test_end_to_end_coord_fills_seal_column_and_keeps_legacy_chars(tmp_path, monkeypatch):
    ctx, corpus, page_lines = _setup(tmp_path, monkeypatch)
    on = AlignRefStep().run_page(_with_params(ctx, corpus, "on"), PAGE)["align_ref"]
    off = AlignRefStep().run_page(_with_params(ctx, corpus, "off"), PAGE)["align_ref"]
    assert off.coord == [] and off.coord_cols == []
    assert [c.model_dump() for c in on.chars] == [c.model_dump() for c in off.chars], \
        "坐标对位不许改现役 chars"
    assert on.coord_cols == [1, 2, 3], on.coord_fallback
    got = {c.id: c.ref_char for c in on.coord}
    assert got[f"{BOOK}:{PAGE}:1:1"] == got[f"{BOOK}:{PAGE}:1:2"] == ""
    assert "".join(got[f"{BOOK}:{PAGE}:1:{s}"] for s in range(3, 22)) == page_lines[0]
    assert "".join(got[f"{BOOK}:{PAGE}:3:{s}"] for s in range(1, 20)) == page_lines[2]


def test_auto_mode_needs_line_per_column_corpus(tmp_path, monkeypatch):
    """`auto`：整段录入的整理本（行远长于每列格数）不做坐标对位。"""
    ctx, corpus, _ = _setup(tmp_path, monkeypatch)
    long = tmp_path / "long.txt"
    long.write_text("\n".join("".join(_uniq_lines(40))[i:i + 200] for i in range(0, 760, 200)),
                    encoding="utf-8")
    r = AlignRefStep().run_page(_with_params(ctx, str(long), "auto"), PAGE)["align_ref"]
    assert r.coord == []


def test_column_shifted_by_one_is_rejected():
    """vol01 p102 列6（职名页，页锚不上）：几何配上了，但认出来的字整列在下一格——错位，退回。"""
    (ln,) = C.parse_lines("天文算法纂修官")
    carriers = "一天文算法纂修"        # 格数、几何都对得上，认出来的字却整列在下一格
    units = [_cu(s, float(s), ch) for s, ch in enumerate(carriers, start=1)]
    r = C.coord_column(units, ln)
    assert not r.ok and "错位" in r.note


def test_grid_corpus_uses_start_and_pipe_notes():
    """P 道逐列本：`#@` 半叶头、全角空格＝格位、`<右|左>`、空列留行。"""
    raw = "#@ 0001 1-1a h0\n欽定\n\n　　元許<兩江|採進本>\n"
    lines = C.parse_lines(raw)
    assert [ln.leaf_start for ln in lines] == [True, False, False]
    assert lines[1].n == 0
    tu = lines[2].text_units()
    assert [p for p, _u in tu] == [2, 3, 4, 5, 6]
    assert [(u.a, u.b) for _p, u in tu if u.kind == "n"] == [("兩", "採"), ("江", "進"), ("", "本")]


# ── 少一格（并格）共识救援（2026-09-30，L1 道 overview#318）──────────────────
_P3_COL1_G = [1.02, 2.0, 3.07, 4.25, 5.4, 6.61, 7.74, 8.74, 9.87, 10.97, 11.95, 13.0, 14.06]
_P3_COL1_CARRIER = "輾定撫雙書總報卷閱蘇攀琴準"


def _p3_col1(carrier=_P3_COL1_CARRIER):
    (ln,) = C.parse_lines("欽定四庫全書總目巻")
    return [_cu(i + 1, g, carrier[i]) for i, g in enumerate(_P3_COL1_G)], ln


def test_merge_rescue_p3_title_column_gives_only_consensus_cells():
    """vol02 p3 列1 实数：9 字标题被切成 8 格（+5 印章假格）。并格位置分不出（四庫/庫全/全書
    并列），所以只给共识格——1、2、6、7、8 格出字，3/4/5 格不出记录；印章格记空格位。"""
    units, ln = _p3_col1()
    r = C.coord_column(units, ln)
    assert r.ok and r.merged and not r.unique
    got = {t[0]: t[3] for t in r.recs}
    assert [got.get(f"id{s}") for s in range(1, 9)] == ["欽", "定", None, None, None, "總", "目", "巻"]
    assert all(got[f"id{s}"] == "" for s in range(9, 14))


def test_merge_rescue_refuses_without_carrier_evidence():
    """载体一个字都不吻合：并格救援不认（宁可空着也不错配），整列仍退回。"""
    units, ln = _p3_col1("某" * 13)
    r = C.coord_column(units, ln)
    assert not r.ok and not r.merged


def test_merge_rescue_never_touches_columns_that_match_one_to_one():
    """格数对得上的列走原路，`merged` 恒为 False、记录与救援无关。"""
    (ln,) = C.parse_lines("元許衡撰")
    r = C.coord_column([_cu(s, s + 2.0, "某") for s in range(1, 5)], ln)
    assert r.ok and not r.merged
