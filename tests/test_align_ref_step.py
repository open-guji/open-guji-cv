# -*- coding: utf-8 -*-
"""Step5-d 整理本对齐（阶段归位，2026-09-09）。

`align_ref` 从 `gold/v2_align.py` 里独立出来，成为与 `glyph_match`/
`ocr_candidates`/`context_decision` 平级的正式 Step；`gold.v2_align.align_page`
改成优先读它的产物再派生 `GoldChar`。这里守两条：

1. Step 本身：注册、`consumes`/`needs`、语料指纹进参数哈希；
2. 两个身份没有互相污染：`align_page` 读 `align_ref` 缓存 与 **不经缓存现算
   一遍**（脚本传非默认语料时的兜底路径）必须给出完全相同的结果——这是
   本次重组"纯重组不改变任何裁决"的核心保证，别的测试测不到这条。
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.engine import params_hash
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.step import KINDS, STEPS
from open_guji_cv.core.workspace import corpus_path
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.align_ref import AlignRefParams

REPO = Path(__file__).resolve().parent.parent


def _ws_raw():
    """原图根：优先 GUJI_WORKSPACE（数据已迁 siku-zongmu-workspace），
    没设则退回仓根——引擎自带的小样本仍在仓内。"""
    from open_guji_cv.core.workspace import raw_root
    return raw_root()
RAW = _ws_raw() / "data_full" / "zongmu"
needs_raw = pytest.mark.skipif(not RAW.exists(), reason="需要 data_full/zongmu 原图")


def test_registered():
    assert "align_ref" in STEPS and "align_ref" in KINDS
    assert "corpus" in STEPS["align_ref"].spec.needs
    # 2026-09-10 去掉对 context_decision 的依赖（不再借 Step6 的定字拼锚定串，
    # 见 align_ref.py 模块头「2026-09-10」一节）——四路才真正互相独立。
    assert set(STEPS["align_ref"].spec.consumes) == {"glyph_match", "ocr_candidates"}


def test_corpus_fingerprint_lands_in_params_and_moves_the_hash():
    """语料换了同一批对齐结论就会变——指纹必须进参数、进哈希（同 context_decide）。"""
    p = AlignRefParams()
    assert p.corpus_fingerprint
    a = AlignRefParams(corpus_fingerprint="aaaa")
    b = AlignRefParams(corpus_fingerprint="bbbb")
    assert params_hash(a) != params_hash(b)


@needs_raw
def test_align_ref_product_reads_as_continuous_prose():
    """端到端产出要读得通——这是"对齐挪出来"之后的唯一整体验收（同
    `test_context_decide_step.test_decided_text_reads_as_continuous_prose`）。"""
    store = ProductStore()
    ar = store.read("vol01", "align_ref", page_key(24), "align_ref")
    if ar is None:
        pytest.skip("还没跑过 align_ref")
    assert ar.anchored
    c1 = sorted((c for c in ar.chars if c.col == 1), key=lambda c: c.slot)
    text = "".join(c.align_char for c in c1)
    for anchor in ("文華殿", "文淵"):
        assert anchor in text, f"c1 对齐字读出来是「{text}」，缺锚点 {anchor}"


@needs_raw
def test_gold_derivation_matches_between_cached_and_live_recompute(tmp_path):
    """核心保证：读 `align_ref` 缓存 与 不经缓存现算一遍，`GoldChar` 必须逐条相同。

    `gold.v2_align.align_page` 现在两条路都会走到（默认语料走缓存，脚本传
    自定义语料走现算兜底，见该模块 `_aligned_chars` 的模块头）——这条测试
    钉住两条路径算法完全一致，不是"看着都能跑"那种巧合。
    """
    from open_guji_cv.gold.v2_align import align_book

    store = ProductStore()
    if store.read("vol01", "align_ref", page_key(24), "align_ref") is None:
        pytest.skip("还没跑过 align_ref")

    cached = align_book("vol01", [24], store)
    # 内容相同、路径不同的语料副本：指纹（按路径 mtime/size 算）必然对不上
    # 缓存的 corpus_fingerprint，强制走现算兜底路径。
    copy = tmp_path / "corpus_copy.txt"
    copy.write_text(corpus_path("zongmu_wuyingdian_reference.txt").read_text(encoding="utf-8"),
                    encoding="utf-8")
    live = align_book("vol01", [24], store, corpus_path=copy)

    assert cached[0].anchored and live[0].anchored
    assert [asdict(c) for c in cached[0].chars] == [asdict(c) for c in live[0].chars]
