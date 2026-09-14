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
    #
    # 2026-09-13：`ocr_candidates` 从 consumes 挪到 optional_consumes。**吃的证据
    # 没变**（仍是库匹配 + OCR 两路），变的是缺席时怎么办：它是书级开关
    # `BookSpec.ocr_candidates` 控制的可选步骤（默认关，`Engine._enabled` 直接把它
    # 滤出 steps），写在 consumes 里会让指纹层 `upstream_shas` 认它是硬依赖、短路
    # 阻塞整步——而 `run_page` 早就用 `_opt()` 兜住了缺席（只在 match 和 ocr 都缺
    # 时才报错）。声明与实现对不上，vol01（开关关着）因此**整条 Step5-d/6/C1 全部
    # 阻塞**，`test_core_v2.test_keben_body_v2_on_vol01_page24` 一直挂在这上面。
    assert set(STEPS["align_ref"].spec.consumes) == {"glyph_match"}
    assert set(STEPS["align_ref"].spec.optional_consumes) == {"ocr_candidates"}


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
    # ⚠️ 有产物 ≠ 锚得上：**同名语料有两份**，仓内 `corpus/` 那份只有 17KB
    # （样本），工作区那份 8.2MB（真语料），差 470 倍。默认环境（什么都不设）
    # 下 `DEFAULT_CORPUS` 解析到仓内样本，拿它去锚真产物必然「8-gram 锚定失败」。
    # 上面那道 skip 只查了产物在不在，漏了语料够不够——锚不上时根本没有 GoldChar
    # 可比，这条测试也就无从测起。要真跑它：**只设 GUJI_WORKSPACE**，让 corpus /
    # products / cache 三者配套指向工作区（别额外设 GUJI_PRODUCTS_DIR，会让
    # products 与 cache 分家，见 test_v2_align_gold 模块头）。
    if not cached[0].anchored:
        pytest.skip(f"锚不上（{cached[0].note}）——多半是在用仓内样本语料")
    # 内容相同、路径不同的语料副本：指纹（按路径 mtime/size 算）必然对不上
    # 缓存的 corpus_fingerprint，强制走现算兜底路径。
    #
    # 2026-09-13 订正：这里曾经复制的是 `zongmu_wuyingdian_reference.txt`
    # （武英殿参考本，34.5 万字）而不是 `align_book`/`AlignRefStep` 两边
    # `DEFAULT_CORPUS` 真正用的 `zongmu_wenyuange_wikisource.txt`（文渊阁
    # wikisource 本，278.8 万字）——两个文件内容完全不同（不是同内容换
    # 路径），"现算"分支实际是拿一部小得多的参考本去锚同一批字位。字位本身
    # 179/179 全部锚上且逐字相同，只有 `op_run`（equal/replace 段长度，
    # 由 `difflib` 按整段上下文切出来）从 63 变 139——语料越短，能与查询串
    # 连续匹配的窗口越容易被判成一整段大 equal，段长自然变。这是**测试
    # fixture 抄错了文件名**（`eb7f93c2e7` 建这条测试时就写死了这个文件，
    # 一直没被执行到，直到 vol01 page24 的 align_ref 产物就位才真正跑到这
    # 里），不是 `align_page`/`_aligned_chars`/`label_page` 算法在两条路径
    # 上分叉——把复制源换成默认语料自身（同内容、只是落盘到另一个临时路径，
    # 才是这条测试真正想测的「缓存 vs 现算，语料给的信息完全一致时必须逐条
    # 相同」）后，两边逐条相同，包括 op_run。
    from open_guji_cv.gold.v2_align import DEFAULT_CORPUS as GOLD_DEFAULT_CORPUS
    copy = tmp_path / "corpus_copy.txt"
    copy.write_text(Path(GOLD_DEFAULT_CORPUS).read_text(encoding="utf-8"), encoding="utf-8")
    live = align_book("vol01", [24], store, corpus_path=copy)

    assert cached[0].anchored and live[0].anchored
    assert [asdict(c) for c in cached[0].chars] == [asdict(c) for c in live[0].chars]
