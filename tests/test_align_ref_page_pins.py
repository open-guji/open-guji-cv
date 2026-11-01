# -*- coding: utf-8 -*-
"""`align_ref` 页钉位（`page_pins`，2026-10-28，GUJI-750 史记文渊阁）。

手写本冷启动，载体串全是乱码、8-gram 锚不上；但我们的页与整理本半叶的对应是确定的，
所以给一份 `{book, page, head}` 钉位表，直接按半叶头定窗口起点 / 列→行。
钉住：半叶头进行表、钉位只在配了且找得到半叶头时生效、坐标对位按半叶头对列、
现役对位以半叶起点为窗口（乱码载体也能对上）、对不上不硬出标签、没配钉位时参数 dump 不变。
"""
from __future__ import annotations

import json

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, write_product
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.recog import ColumnMatch, MatchRec, PageMatch
from open_guji_cv.steps import align_ref as A
from open_guji_cv.steps import align_ref_coord as C
from open_guji_cv.steps.align_ref import AlignRefParams, AlignRefStep

BOOK, PAGE = "tbook", 1
HEADS = ["0243-0005 243-1b h0", "0243-0005 243-1b h1", "0243-0008 243-2a h0"]


def _body(n, width=8):
    base = 0x4E00
    return ["".join(chr(base + i * width + k) for k in range(width)) for i in range(n)]


def _grid(tmp_path):
    body = _body(24)
    raw = "".join(f"#@ {h}\n" + "\n".join(body[k * 8:(k + 1) * 8]) + "\n" for k, h in enumerate(HEADS))
    corpus = tmp_path / "grid.txt"
    corpus.write_text(raw, encoding="utf-8")
    return body, str(corpus)


def _pins(tmp_path, monkeypatch, rows):
    f = tmp_path / "pins.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(A, "_pin_file", lambda name: f)
    A._page_pin_heads.cache_clear()
    A._head_index.cache_clear()
    return "pins.jsonl"


def test_parse_lines_keeps_leaf_head_text(tmp_path):
    _body_, corpus = _grid(tmp_path)
    lines, _ = C.ref_lines(corpus)
    heads = {ln.head: ln.idx for ln in lines if ln.leaf_start}
    assert heads == {HEADS[0]: 0, HEADS[1]: 8, HEADS[2]: 16}
    assert all(ln.head == "" for ln in lines if not ln.leaf_start)


def test_page_pin_resolves_line_and_han_offset(tmp_path, monkeypatch):
    _b, corpus = _grid(tmp_path)
    name = _pins(tmp_path, monkeypatch, [{"book": BOOK, "page": 1, "head": HEADS[1]},
                                         {"book": BOOK, "page": 2, "head": "不存在 的 头"}])
    p = AlignRefParams(corpus=corpus, page_pins=name)
    assert A.page_pin(p, BOOK, 1) == (HEADS[1], 8, 64)       # 第 2 个半叶：前面 8 列 × 8 字
    assert A.page_pin(p, BOOK, 2) is None                    # 头在整理本里找不到 → 当没钉
    assert A.page_pin(p, BOOK, 3) is None                    # 没钉这页
    assert A.page_pin(p, "别册", 1) is None                   # 钉位按册分
    assert A.page_pin(AlignRefParams(corpus=corpus), BOOK, 1) is None


def test_pin_map_columns_follow_leaf_head_and_stay_inside_leaf(tmp_path):
    body, corpus = _grid(tmp_path)
    lines, _ = C.ref_lines(corpus)
    carriers = [(c, body[8 + c - 1]) for c in range(1, 10)]   # 第 9 列已出本半叶
    pm = A._pin_map(carriers, lines, 8)
    assert pm.base == 8 and pm.col_line == {c: 8 + c - 1 for c in range(1, 9)}
    assert pm.past_leaf == [9]                                 # 过了本半叶末行的列单记（align_ref 2.5）
    # 整页载体乱码：不靠载体定位，列照样按半叶头对上
    pm = A._pin_map([(c, "龘龘龘龘") for c in range(1, 9)], lines, 16)
    assert pm.col_line == {c: 16 + c - 1 for c in range(1, 9)}


def _page(ctx, body_leaf, garbage):
    cols_m, cols_c = [], []
    for ci, text in enumerate(body_leaf, start=1):
        mrecs, crecs = [], []
        for i, ch in enumerate(text):
            slot = i + 1
            mrecs.append(MatchRec(id=f"{BOOK}:{PAGE}:{ci}:{slot}", slot=slot, verdict="unsure", cov=0.5,
                                  candidates=[("龘" if garbage else ch, 0.5)]))
            crecs.append(CellRec(slot=slot, pos=slot, y0=i * 100, y1=(i + 1) * 100, x0=0, x1=100,
                                 kind="char", order=i))
        cols_m.append(ColumnMatch(col=ci, ok=True, chars=mrecs))
        cols_c.append(ColumnCells(col=ci, ok=True, n_body_slots=8, period=100.0, border_top=0.0, cells=crecs))
    write_product(ctx, "glyph_match", PAGE, glyph_match=PageMatch(page=PAGE, columns=cols_m))
    write_product(ctx, "row_segment", PAGE, cells=PageCells(page=PAGE, period=100.0, ref_w=100.0, columns=cols_c))


def _run(ctx, corpus, pins):
    from open_guji_cv.core.step import RunContext
    p = AlignRefParams(corpus=corpus, coord="on", page_pins=pins)
    return AlignRefStep().run_page(
        RunContext(ctx.book, ctx.store, ctx.cache, params={"align_ref": p}, log=lambda s: None), PAGE)["align_ref"]


def test_pinned_page_aligns_even_when_carrier_is_mostly_wrong(tmp_path, monkeypatch):
    """载体 3/4 认错（8-gram 一个都不会命中）：不钉锚不上；钉了就以半叶起点为窗口，equal 字出标签。"""
    body, corpus = _grid(tmp_path)
    leaf = body[8:16]
    # 每列只保留第 1、2、5、6 字对的（连续对的 ≤2，凑不出 8-gram）
    noisy = ["".join(ch if k in (0, 1, 4, 5) else "龘" for k, ch in enumerate(t)) for t in leaf]
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    _page(ctx, noisy, garbage=False)
    free = _run(ctx, corpus, "")
    assert not free.anchored
    name = _pins(tmp_path, monkeypatch, [{"book": BOOK, "page": PAGE, "head": HEADS[1]}])
    pinned = _run(ctx, corpus, name)
    assert pinned.anchored and pinned.anchor_via == "pin"
    got = {c.id: c.align_char for c in pinned.chars if c.align_op == "equal"}
    assert got[f"{BOOK}:{PAGE}:3:1"] == leaf[2][0]
    # 坐标对位：整列按半叶头配，不依赖认字
    assert pinned.coord_cols == list(range(1, 9)), pinned.coord_fallback
    assert "页钉位" in pinned.coord_note


def test_pinned_but_unmatched_page_is_not_forced(tmp_path, monkeypatch):
    """钉了但整页对不上（表页、半叶头钉错）：不拿错窗口硬出标签，note 写明。"""
    body, corpus = _grid(tmp_path)
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    _page(ctx, body[16:24], garbage=False)      # 实际是第 3 个半叶
    name = _pins(tmp_path, monkeypatch, [{"book": BOOK, "page": PAGE, "head": HEADS[0]}])   # 钉错成第 1 个半叶
    r = _run(ctx, corpus, name)
    assert not r.anchored and "页钉位" in r.note and r.chars == []


def test_page_pins_off_leaves_params_dump_and_hash_unchanged():
    d = AlignRefParams(corpus="x").model_dump()
    assert "page_pins" not in d and "page_pins_fingerprint" not in d and "pin_min_equal_frac" not in d
    on = AlignRefParams(corpus="x", page_pins="pins.jsonl").model_dump()
    assert on["page_pins"] == "pins.jsonl" and on["page_pins_fingerprint"]
