"""字流证人对齐（`utils/witness_align_stream.py`）：同书异版、换行对不上时的标签来源。

要点：标签一律取**证人字**（OCR 只当锚）；只收长度 ≥ min_block 的 `equal` 块；
`replace` 块（OCR 与证人不一致，可能是 OCR 错也可能是异文）整块跳过，不猜。
"""
import json

from open_guji_cv.utils.witness_align_stream import (align_stream, book_cell_stream,
                                                     witness_char_stream, write_labels)


class _Book:
    id = "tb"
    references = [{"file": "w.txt"}]


def _write_products(root, pages):
    """pages: {page: [(col, kind, [(slot, cell_kind), ...]), ...]}"""
    for pg, cols in pages.items():
        rs = {"cells": {"page": pg, "period": 70.0, "ref_w": 100.0, "columns": [
            {"col": c, "ok": True, "cells": [
                {"slot": s, "kind": k, "ink_ratio": 0.2} for s, k in cells]}
            for c, _kind, cells in cols]}}
        (root / "tb" / "row_segment").mkdir(parents=True, exist_ok=True)
        (root / "tb" / "row_segment" / f"p{pg:04d}.json").write_text(
            json.dumps(rs, ensure_ascii=False), encoding="utf-8")
        li = {"line_index": {"page": pg, "width": 100, "height": 100, "n_body": len(cols),
                             "lines": [{"col": c, "kind": kind, "x0": 0.0, "x1": 1.0,
                                        "y0": 0.0, "y1": 1.0, "width": 1.0, "flags": []}
                                       for c, kind, _ in cols]}}
        (root / "tb" / "border_detect").mkdir(parents=True, exist_ok=True)
        (root / "tb" / "border_detect" / f"p{pg:04d}.json").write_text(
            json.dumps(li, ensure_ascii=False), encoding="utf-8")


def _write_ocr(root, pg, cols):
    doc = {"ocr_candidates": {"page": pg, "engine": "t", "columns": [
        {"col": c, "ok": True, "error": None, "chars": [
            {"slot": s, "sub": None, "id": f"tb:{pg}:{c}:{s}", "engine": "t",
             "topk": [[ch, 0.9]]} for s, ch in items]}
        for c, items in cols]}}
    (root / "tb" / "ocr_candidates").mkdir(parents=True, exist_ok=True)
    (root / "tb" / "ocr_candidates" / f"p{pg:04d}.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_witness_stream_strips_punct_pagemarks_and_footnotes(tmp_path):
    w = tmp_path / "w.txt"
    w.write_text("春秋，時屬。\n0012\n①這是腳註\n鮮虞國也\n", encoding="utf-8")
    assert witness_char_stream(w) == "春秋時屬鮮虞國也"


def test_cell_stream_skips_margin_and_non_body_columns(tmp_path):
    root = tmp_path / "products"
    _write_products(root, {1: [
        (1, "body", [(1, "char"), (2, "char")]),
        (2, "margin", [(1, "char")]),          # 版心：必须跳过
        (3, "edge", [(1, "char")]),            # 页边：必须跳过
        (4, "body", [(1, "char"), (2, "blank")]),   # blank 不进字流
    ]})
    cells = book_cell_stream(root, "tb")
    assert [(c.col, c.slot) for c in cells] == [(1, 1), (1, 2), (4, 1)]


def test_labels_come_from_witness_and_only_from_long_equal_blocks(tmp_path):
    root = tmp_path / "products"
    text = "春秋時屬鮮虞國爲晉所滅戰國屬趙"          # 15 字
    _write_products(root, {1: [(1, "body", [(i + 1, "char") for i in range(len(text))])]})
    # OCR 第 5 个字读错（滅→減 之类），其余全对
    ocr = list(text)
    ocr[4] = "解"
    _write_ocr(root, 1, [(1, [(i + 1, ch) for i, ch in enumerate(ocr)])])
    w = tmp_path / "w.txt"
    w.write_text(text, encoding="utf-8")

    res = align_stream(_Book(), witness=w, products_root=root, min_block=4, log=lambda *a: None)
    got = {(d["slot"]): d["char"] for d in res.labels}
    # 错读那一位落在 replace 块里，两侧的 equal 块（长 4 与 10）都过闸
    assert 5 not in got, "OCR 与证人不一致的位置不该给标签"
    assert got[1] == "春" and got[15] == "趙"
    # 标签取的是证人字，不是 OCR 字
    assert all(got[i + 1] == ch for i, ch in enumerate(text) if i + 1 in got)
    assert res.ocr_agree == res.n_labeled  # equal 块里两者按定义一致


def test_short_equal_blocks_are_dropped(tmp_path):
    root = tmp_path / "products"
    text = "春秋時屬鮮虞國也"
    _write_products(root, {1: [(1, "body", [(i + 1, "char") for i in range(len(text))])]})
    ocr = list(text)
    ocr[2] = "X"          # 把字流切成 2 + 5 两个 equal 块
    _write_ocr(root, 1, [(1, [(i + 1, ch) for i, ch in enumerate(ocr)])])
    w = tmp_path / "w.txt"
    w.write_text(text, encoding="utf-8")

    hi = align_stream(_Book(), witness=w, products_root=root, min_block=6, log=lambda *a: None)
    assert hi.n_labeled == 0, "两个块都短于 6，应当一个标签都不给"
    lo = align_stream(_Book(), witness=w, products_root=root, min_block=2, log=lambda *a: None)
    assert lo.n_labeled == 7


def test_missing_ocr_does_not_fabricate_labels(tmp_path):
    """没有 OCR 产物时字流全是占位符，匹配不上——宁可 0 个标签也不能瞎给。"""
    root = tmp_path / "products"
    text = "春秋時屬鮮虞國也"
    _write_products(root, {1: [(1, "body", [(i + 1, "char") for i in range(len(text))])]})
    w = tmp_path / "w.txt"
    w.write_text(text, encoding="utf-8")
    res = align_stream(_Book(), witness=w, products_root=root, min_block=4, log=lambda *a: None)
    assert res.n_labeled == 0


def test_write_labels_roundtrip_is_seed_witness_shaped(tmp_path):
    root = tmp_path / "products"
    text = "春秋時屬鮮虞國也"
    _write_products(root, {1: [(1, "body", [(i + 1, "char") for i in range(len(text))])]})
    _write_ocr(root, 1, [(1, [(i + 1, ch) for i, ch in enumerate(text)])])
    w = tmp_path / "w.txt"
    w.write_text(text, encoding="utf-8")
    res = align_stream(_Book(), witness=w, products_root=root, min_block=4, log=lambda *a: None)
    out = tmp_path / "labels.jsonl"
    write_labels(res, out)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == len(text)
    # seed_witness 消费的那几个键必须在
    for r in rows:
        assert set(("page", "col", "slot", "char", "kind", "cell_kind")) <= set(r)
        assert r["kind"] == "char" and r["cell_kind"] == "char"
