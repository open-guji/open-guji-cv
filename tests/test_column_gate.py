# -*- coding: utf-8 -*-
"""Step2→3 交接闸的判据分层。

守住 2026-09-03 的那次改动：**列宽偏离是列级判据，不是页级**。
它逐列算得出，却曾被放在页级拒因里 —— 一列坏就整页 9 列作废。
实证见 doc/step3_error_survey.md 乙类（vol01/42 八列完好只因 c9 坏而全废）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.core.book import load_book
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.spec import page_key
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def _gate(book: str, page: int):
    """跑到闸为止，返回 gate_manifest（用真实产物缓存，不重算上游）。"""
    store = ProductStore()
    g = store.read(book, "column_gate", page_key(page), "gate_manifest")
    if g is None:
        pytest.skip(f"{book}/{page} 还没跑过闸")
    return g


@needs_raw
def test_wide_column_blocks_only_itself_not_whole_page():
    """列宽异常只拦本列，不拖累整页。

    原来钉的是 vol01/42 c9（宽 218 对中位 187，+16.6%）——**2026-09-04
    合并 main 之后这个缺陷没了**：Step1 换成「最外线粗外条 → 细内框次候选」
    以后，该页九列宽度是 180~197、中位 187，c9 已在 ±15% 内，整页放行。
    靶子消失是好事，但断言不能跟着消失，否则「列宽回到页级」这个回归就没人守。
    改成在全 dev_set 上找任意一个被 L1c 拦的列，验证它只拦自己。
    """
    store = ProductStore()
    found = False
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            d = store.read_raw(book, "column_gate", page_key(pg))
            if not d:
                continue
            gm = d["gate_manifest"]
            hit = [c for c in gm["columns"]
                   if any("L1c" in r for r in c["reject"])]
            if not hit:
                continue
            found = True
            # 这条测试守的是**「列宽异常不上升为页级拒因」**，只该断言这一点。
            # 「至少有一列可用」不成立：vol02/177 整页没有印刷界行，L1c 拦了
            # 2 列、其余被 L2（边缘墨）拦光，可用列 0——那是该页的真实情况，
            # 不是列宽判据回到了页级。
            assert gm["admitted"], f"{book}/{pg} 页级不该因单列宽度而拒绝"
            for c in gm["columns"]:
                if any("L1c" in r for r in c["reject"]):
                    continue
                assert not any("L1c" in r for r in c["reject"]), "不可能"
            assert not any("列宽" in r for r in gm["reject"]),                 f"{book}/{pg} 页级拒因里出现了列宽：{gm['reject']}"
    if not found:
        pytest.skip("当前 dev_set 上没有列宽异常的列——Step1 修好之后是可能的")


@needs_raw
def test_page_priors_survive_dropping_wide_column():
    """页级 period / ref_w 由几何正常的列算出，异常列被剔除后仍在健康区间。"""
    for book, page in [("vol01", 42), ("vol02", 3), ("vol02", 119)]:
        g = _gate(book, page)
        if not g.admitted:
            continue
        assert g.period is not None and 100 <= g.period <= 125, \
            f"{book}/{page} period={g.period} 落在正文页健康区间外"
        assert g.ref_w is not None and 140 <= g.ref_w <= 210


@needs_raw
def test_page_level_still_rejects_wrong_column_count():
    """列数不对仍是页级问题——整页的列编号和窗口一起错位，单列救不回来。"""
    store = ProductStore()
    found = False
    for pg in load_book("vol02").all_pages():
        d = store.read_raw("vol02", "column_gate", page_key(pg))
        if not d:
            continue
        gm = d["gate_manifest"]
        if not gm["admitted"] and any("只探出" in r for r in gm["reject"]):
            found = True
            assert all(not c["admitted"] for c in gm["columns"]), \
                "列数不对时整页都该拒绝"
            break
    if not found:
        pytest.skip("本册没有列数不对的页")


@needs_raw
def test_width_reject_never_appears_at_page_level():
    """列宽偏离只能出现在列级 reject 里，页级拒因不许再有它。

    查行为而不是查源码文本——注释里提到「列宽」是正常的。
    """
    store = ProductStore()
    checked = 0
    for book in ("vol01", "vol02"):
        for pg in load_book(book).all_pages():
            d = store.read_raw(book, "column_gate", page_key(pg))
            if not d:
                continue
            gm = d["gate_manifest"]
            checked += 1
            for r in gm["reject"]:
                assert "列宽" not in r, f"{book}/{pg} 页级拒因里还有列宽：{r}"
    if not checked:
        pytest.skip("还没有闸产物")


@needs_raw
def test_top_flush_column_gets_slack_even_without_a_head_raise_box():
    """版框平齐但顶端有字墨的**顶格列**也要拿到 top_slack。

    钉住 2026-09-03 的 A2 第一刀。原先只有 `raised`（Step1 探到抬头**框**、
    版框有台阶）才给 slack，而这批书里更常见的是版框平齐、字从版框内顶端
    起写——`raised=False`、`border_top_in_column=0`、`top_slack=0`，DP 首锚点
    窗口开不上去，首字被压在格顶。vol01/141 c7「諭旨」是实锤。
    """
    g = _gate("vol01", 141)
    c7 = next(c for c in g.columns if c.col == 7)
    assert not c7.raised, "141 c7 版框是平齐的（不是抬头框型）"
    assert c7.top_slack > 0, "顶格列应当拿到 slack"

    # 同页的普通正文列不该被误判成顶格
    plain = [c for c in g.columns if c.col in (1, 2, 3)]
    assert all(c.top_slack == 0 for c in plain), \
        f"正文列不该有 slack：{[(c.col, c.top_slack) for c in plain]}"


@needs_raw
def test_top_flush_detection_does_not_fire_on_every_column():
    """顶格检测要有选择性——全命中等于没判据。"""
    store = ProductStore()
    hit = total = 0
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            d = store.read_raw(book, "column_gate", page_key(pg))
            if not d:
                continue
            for c in d["gate_manifest"]["columns"]:
                total += 1
                if c["top_slack"] > 0 and not c["raised"]:
                    hit += 1
    if not total:
        pytest.skip("还没有闸产物")
    assert 0 < hit < total * 0.5, \
        f"顶格列 {hit}/{total}——判据要么没生效要么全命中"


@needs_raw
def test_bottom_bound_reaches_past_the_frame_line():
    """交给 Step3 的下界要落在版框线**之外**，否则末字够不到。

    钉住 2026-09-03 的 A4 一刀。Step3 的 candN 窗口上界就是这个 border_bottom，
    传版框线的话，末字只要压着版框写、末边界就永远够不到它——实测 dev_set
    216 列中 147 列（68%）真末墨超出版框线，末格 y1 比真末墨低中位 11px，
    slot 21 因此占了 R4 被切总数的 57%。
    """
    store = ProductStore()
    checked = beyond = 0
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            g = store.read(book, "column_gate", page_key(pg), "gate_manifest")
            w = store.read(book, "column_warp", page_key(pg), "column_windows")
            if g is None or w is None:
                continue
            for gc in g.columns:
                wc = next((x for x in w.columns if x.col == gc.col), None)
                if wc is None:
                    continue
                checked += 1
                assert gc.border_bottom >= wc.border_bottom_in_column, \
                    f"{book}/{pg}c{gc.col} 下界跑到版框线里面了"
                assert gc.border_bottom <= wc.warped_size[1], \
                    f"{book}/{pg}c{gc.col} 下界超出列图"
                if gc.border_bottom > wc.border_bottom_in_column:
                    beyond += 1
    if not checked:
        pytest.skip("还没有闸产物")
    assert beyond > checked * 0.8, \
        f"只有 {beyond}/{checked} 列的下界越过版框线——bottom_slack 没生效？"


@needs_raw
def test_n_raised_hint_is_per_column_not_page_wide():
    """「抬头多一个字」是逐列的，闸要按墨跨度逐列给出 hint。

    钉住 2026-09-03 的 A2 收尾。`n_raised` 原先只有页级参数一个来源，
    而同一页上有的抬头列多一格、有的只是整体上挪（vol01/33 四个抬头列
    实测 3 个多一字、1 个不多）。给不出逐列值时 DP 只能在 21 格里硬塞
    22 个字，唯一可行解是**丢掉首字**——实测 vol01/26c6、33c7/c8、
    47c6/c9 的墨跨度 / period 达 21.4~22.2。
    """
    store = ProductStore()
    hits = pages_with_mixed = 0
    total = 0
    for book in ("vol01", "vol02"):
        for pg in load_book(book).dev_set:
            d = store.read_raw(book, "column_gate", page_key(pg))
            if not d:
                continue
            vals = [c.get("n_raised_hint", 0) for c in d["gate_manifest"]["columns"]]
            total += len(vals)
            hits += sum(1 for v in vals if v)
            if any(vals) and not all(vals):
                pages_with_mixed += 1
    if not total:
        pytest.skip("还没有闸产物")
    assert hits, "hint 一列都没命中——判据没生效？"
    assert hits < total * 0.2, f"hint 命中 {hits}/{total}，太多了，判据可能过松"
    assert pages_with_mixed, \
        "没有一页是「部分列有 hint」——那就说明它其实还是页级的，白改了"


@needs_raw
def test_vol01_33_head_raise_columns_differ():
    """vol01/33 是逐列差异的实证页：同页抬头列有的多一格、有的不多。"""
    store = ProductStore()
    d = store.read_raw("vol01", "column_gate", page_key(33))
    if not d:
        pytest.skip("vol01/33 还没跑过闸")
    hints = {c["col"]: c.get("n_raised_hint", 0) for c in d["gate_manifest"]["columns"]}
    assert hints.get(7) or hints.get(8), "33 c7/c8 的墨跨度够 22 字，该给 hint"
    assert not all(hints.values()), "同页不该所有列都多一格"
