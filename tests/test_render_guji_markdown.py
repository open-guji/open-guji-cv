# -*- coding: utf-8 -*-
"""Step9 结果整理 · 坐标转字符位回归集（`open-guji-dataset` `guji-markdown-render`）。

跟 `test_align_anchor_bench.py` 同一个模式：分片自带最小快照（一页的
`cells`/`seed_admit` 关键字段），不依赖真实 `products/`，不需要
`GUJI_WORKSPACE`。

`expected.text` 是**固化的当前真实输出**，不是"已验证绝对正确"的人工金标
——`render:vol01:89` 那条甚至是已知的过期数据案例（见分片 README）。
这条回归集守的是"改 `render_column`/`render_page` 时行为别悄悄跑偏"，
不是"输出内容语义正确"（内容对不对要靠人核对原图，另一件事）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DATASET = Path(__file__).resolve().parent.parent.parent / "open-guji-dataset"
ITEMS = DATASET / "guji-markdown-render" / "items.jsonl"
needs_dataset = pytest.mark.skipif(not ITEMS.exists(), reason="需要 open-guji-dataset")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _load_items() -> list[dict]:
    if not ITEMS.exists():
        return []
    with open(ITEMS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _cells_by_key(col_snap: dict):
    from open_guji_cv.products.kinds.cells import CellRec
    return {(c["slot"], c["sub"] or ""): CellRec(slot=c["slot"], pos=0, y0=0, y1=0,
                                                  x0=0, x1=0, kind=c["kind"],
                                                  sub=c["sub"], order=0)
            for c in col_snap["cells"]}


def _admit_recs(col_snap: dict):
    from open_guji_cv.products.kinds.recog import AdmitRec
    return [AdmitRec(id="", slot=c["slot"], sub=c["sub"], admit=c["admit"],
                      char=c["char"], reading=c["reading"])
            for c in col_snap["chars"]]


@needs_dataset
@pytest.mark.parametrize("item", _load_items(), ids=lambda it: it["id"])
def test_render_matches_expected(item: dict):
    from render_guji_markdown import render_column

    cells_by_col = {c["col"]: c for c in item["input"]["cells"]}
    page = item["input"]["page"]

    stale: list[str] = []
    lines = []
    for col_admit in sorted(item["input"]["seed_admit"], key=lambda c: c["col"]):
        col = col_admit["col"]
        col_snap = cells_by_col.get(col, {"cells": []})
        cells_by_key = _cells_by_key(col_snap)
        n_raised = col_snap.get("n_raised", 0)
        recs = _admit_recs(col_admit)
        col_stale: list[str] = []
        lines.append(render_column(recs, cells_by_key, n_raised, col_stale, col))
        # render_page() 给每条 stale 加 p{page} 前缀，这里手动复现同一约定，
        # 否则 expected.stale（由 render_page 生成）永远对不上。
        stale.extend(f"p{page}{s}" for s in col_stale)

    text = "\n".join(lines)

    assert text == item["expected"]["text"], f"{item['id']}: 渲染结果与固化基线不一致"
    assert sorted(set(stale)) == item["expected"]["stale"], (
        f"{item['id']}: stale 检测结果变了——"
        f"{sorted(set(stale))} != {item['expected']['stale']}")


@needs_dataset
def test_bench_covers_known_pages():
    ids = {it["id"] for it in _load_items()}
    expected_ids = {
        "render:vol01:10", "render:vol01:33",
        "render:vol01:89", "render:vol01:146",
    }
    assert expected_ids <= ids, f"缺失案例：{expected_ids - ids}"
