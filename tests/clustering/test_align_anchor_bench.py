# -*- coding: utf-8 -*-
"""Step5-d 锚定判据回归集（`open-guji-dataset` `char-segmentation/align-anchor`）。

2026-09-11 POOL_RADIUS 3→8 修复时固化下来的案例——见该分片 README：踩坑页
（真锚点因页内多处漏字/多字飘移 9~12 位，合并半径不够会被误判失败）、
正常对照页（飘移小，防止以后改动把简单案例改坏）、真实失败反例（目录页，
语料确实未收录，防止判据变得"来者不拒"）。

每条记录自带 `corpus_window`（语料片段，不是整部语料），现建一个窗口专属
的 n-gram 索引——跑 `anchor_page_diag` 不需要 `GUJI_WORKSPACE`/真图/模型。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_guji_cv.clustering.align_eval import anchor_page_diag, build_ngram_index

DATASET = Path(__file__).resolve().parent.parent.parent.parent / "open-guji-dataset"
ITEMS = DATASET / "char-segmentation" / "align-anchor" / "items.jsonl"
needs_dataset = pytest.mark.skipif(not ITEMS.exists(), reason="需要 open-guji-dataset")


def _load_items() -> list[dict]:
    if not ITEMS.exists():
        return []
    with open(ITEMS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@needs_dataset
@pytest.mark.parametrize("item", _load_items(), ids=lambda it: it["id"])
def test_anchor_matches_expected(item: dict):
    text = item["input"]["query_text"]
    window = item["input"]["corpus_window"]
    index = build_ngram_index(window)
    diag = anchor_page_diag(text, index)

    exp = item["expected"]
    assert diag.anchored == exp["anchored"], (
        f"{item['id']}: anchored={diag.anchored} 预期 {exp['anchored']}（{diag.reason}）")
    if exp["anchored"]:
        assert diag.offset == exp["offset_in_window"], (
            f"{item['id']}: offset={diag.offset} 预期 {exp['offset_in_window']}")


@needs_dataset
def test_bench_covers_known_regression_pages():
    """防止分片本身被误删/误改小——这次修复至少要守住 7 个踩坑页 + 1 个反例。"""
    ids = {it["id"] for it in _load_items()}
    regression_ids = {
        "anchor:vol01:5", "anchor:vol01:63", "anchor:vol01:77",
        "anchor:vol03:7", "anchor:vol03:17", "anchor:vol03:33", "anchor:vol03:35",
    }
    assert regression_ids <= ids, f"缺失踩坑案例：{regression_ids - ids}"
    assert "anchor:vol01:184" in ids, "缺失真实失败反例"
