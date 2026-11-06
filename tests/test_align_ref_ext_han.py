# -*- coding: utf-8 -*-
"""对位字流保留扩展区汉字（A24 2026-11-06，A23 诊断）。

原先 `align_ref._corpus_text` 只留 U+4E00–9FFF：整理本里的 㣲 𮅕 𮪍 这类扩展区字被删掉，
整理本少一个字，difflib 在那里断段，前后几格都对不上（殿本 Z01 394 格现役对位缺位里 109 格因此而起）。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_match, write_product
from open_guji_cv.core.step import STEPS
from open_guji_cv.steps.align_ref import AlignRefParams, _corpus_text

BOOK, PAGE, COL = "tbook", 1, 1
EXT = "㣲𢰅𮅕𮪍" + chr(0x31350) + chr(0x323B0)      # 扩A、B、F、F、H、J


def test_corpus_text_keeps_extension_han(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("文華，" + EXT + "〓□、殿\n　閣", encoding="utf-8")
    assert _corpus_text(str(p)) == "文華" + EXT + "殿閣"   # 标点、〓、□、私用区、空白照旧不进


def test_ext_char_in_column_gets_equal_label(tmp_path, monkeypatch, ws):
    left, right = "文華殿大學士臣紀昀等奉敕", "撰欽定四庫全書總目卷一經部"
    chars = left + "𮅕" + right
    corpus = tmp_path / "ref.txt"
    corpus.write_text(("春夏秋冬東西南北" + chars + "金木水火土日月") * 3, encoding="utf-8")
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    ctx.params["align_ref"] = AlignRefParams(corpus=str(corpus))
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, col=COL, recs=[
        dict(slot=i + 1, verdict="same", char=ch, cov=0.999, matched_id=f"g{i}") for i, ch in enumerate(chars)]))
    ar = STEPS["align_ref"].run_page(ctx, PAGE)["align_ref"]
    assert ar.anchored, ar.note
    got = {c.slot: (c.align_char, c.align_op) for c in ar.chars if c.col == COL}
    assert got.get(len(left) + 1) == ("𮅕", "equal"), got
    assert len(got) == len(chars)


def test_coord_offsets_count_extension_han(tmp_path):
    """坐标对位的行起点偏移与 `_corpus_text` 同一把尺子：扩展区字也要数进去，否则偏移→行号错开。"""
    from open_guji_cv.steps.align_ref_coord import parse_lines
    raw = "文" + EXT + "華\n殿閣\n"
    p = tmp_path / "c.txt"
    p.write_text(raw, encoding="utf-8")
    lines = parse_lines(raw)
    assert [ln.han_start for ln in lines] == [0, len(_corpus_text(str(p))) - 2]
