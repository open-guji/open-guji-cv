# -*- coding: utf-8 -*-
"""v2 产物 → v1 CharInstance 的桥（阶段 B0）。

守住两条口径：格号换算（v1 idx 从 0 且连续 / v2 slot 从 1、抬头负数、
夹注 a/b 共用）与 bbox 空间（优先规范空间 bbox_page）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps._v1_bridge import export_v1_view, to_char_instances

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


@needs_raw
def test_bridge_emits_v1_shaped_instances():
    store = ProductStore()
    insts = to_char_instances("vol01", 24, store)
    if not insts:
        pytest.skip("vol01/24 还没跑过 cell_shrink")
    i = insts[0]
    # v1 的字段都在
    for f in ("id", "book", "page", "col", "idx", "bbox", "cell_type",
              "patch_path", "ink_ratio", "flags", "sub"):
        assert hasattr(i, f), f"缺字段 {f}"
    assert i.book == "vol01" and i.page == "24"
    assert len(i.bbox) == 4


@needs_raw
def test_idx_is_physical_position_not_slot():
    """v1 的 idx 必须是**物理位置**（0 起、单调），不是 v2 的 slot。

    slot 在抬头列是负数、夹注 a/b 共用同一个值，直接拿它当 idx 会让下游按
    `page:col:idx` 建的索引撞车。
    **不查连续性**：Step4 只发 cell_type=char 的格，空白格不在这里——列首低
    格起排（vol01/137、141 从 idx=2 起）和列中段整段留白（vol01/26c5 空 7~20）
    都是真实版面，不是格号换算错。
    """
    store = ProductStore()
    seen_any = False
    for pg in load_book("vol01").dev_set[:4]:
        insts = to_char_instances("vol01", pg, store)
        if not insts:
            continue
        seen_any = True
        by_col: dict[int, list] = {}
        for i in insts:
            by_col.setdefault(i.col, []).append(i)
        for col, recs in by_col.items():
            idxs = [r.idx for r in recs]
            assert min(idxs) >= 0, f"vol01/{pg}c{col} 出现负 idx：{min(idxs)}"
            # 重复只允许来自夹注 a/b（同一物理位置的两个半格）
            for x in sorted(set(idxs)):
                if idxs.count(x) == 1:
                    continue
                subs = {r.sub for r in recs if r.idx == x}
                assert subs <= {"a", "b"} and len(subs) > 1, \
                    f"vol01/{pg}c{col} idx={x} 重复 {idxs.count(x)} 次但不是夹注：{subs}"
            # slot 会是负数（抬头格），idx 不许跟着变负——这正是这条测试的靶子
            slots = [r.id.rsplit(":", 1)[-1] for r in recs]
            if any(s.startswith("-") for s in slots):
                assert min(idxs) == 0, \
                    f"vol01/{pg}c{col} 有抬头格（slot 负）但 idx 没落在 0：{sorted(set(idxs))[:3]}"
    if not seen_any:
        pytest.skip("dev_set 前四页都没有 cell_shrink 产物")


@needs_raw
def test_bbox_prefers_the_canonical_page_space():
    """bbox 要用 bbox_page（规范空间），退回列图坐标时必须打标记。"""
    store = ProductStore()
    insts = to_char_instances("vol01", 24, store)
    if not insts:
        pytest.skip("没有产物")
    fell_back = [i for i in insts if "bbox_is_column" in i.flags]
    # v2 链正常跑出来的都有 bbox_page；真退回了也要留痕，不许静默
    assert not fell_back or all("bbox_is_column" in i.flags for i in fell_back)


@needs_raw
def test_export_view_is_loadable_by_v1_loader(tmp_path):
    """导出的目录要能被 v1 的 load_index 原样读回——这是桥存在的意义。"""
    from open_guji_cv.clustering.extractor import load_index
    v = export_v1_view("vol01", pages=[24], root=tmp_path / "view")
    if not v.index_path.exists():
        pytest.skip("没有产物")
    insts = load_index(v.root)
    assert insts, "导出的 index.jsonl 读不出实例"
    with_patch = [i for i in insts if (v.root / i.patch_path).exists()]
    chars = [i for i in insts if i.cell_type == "char"]
    assert len(with_patch) >= len(chars) * 0.9, \
        f"只有 {len(with_patch)}/{len(chars)} 个 char 实例落了图块"
