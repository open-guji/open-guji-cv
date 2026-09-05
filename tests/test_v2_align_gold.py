# -*- coding: utf-8 -*-
"""v2 × 整理本自动金标 + C1 的 near_form 防线。"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import page_key
from open_guji_cv.gold.v2_align import align_book
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data_full" / "zongmu"
CORPUS = REPO / "corpus" / "zongmu_wuyingdian_reference.txt"
needs = pytest.mark.skipif(not (RAW.exists() and CORPUS.exists()),
                           reason="需要原图与整理本")


@needs
def test_most_pages_anchor():
    """dev_set 大多数页要能靠整理本锚上——锚不上就没有金标可言。"""
    st = ProductStore()
    golds = align_book("vol01", load_book("vol01").dev_set, st)
    ok = [g for g in golds if g.anchored]
    if not any(g.n_chars for g in golds):
        pytest.skip("还没跑过 context_decide")
    assert len(ok) >= len(golds) * 0.75, \
        f"只锚上 {len(ok)}/{len(golds)} 页"


@needs
def test_shape_and_reading_are_recorded_separately():
    """字形与文意分开记（用户 2026-09-04 定：先读字形、录入按文意）。

    整理本是正字化文本，刻本上的 㫖/彚/卽/祗 会被它写成 旨/彙/即/祇。
    这个差别必须留痕，不能只存一个。
    """
    st = ProductStore()
    golds = align_book("vol01", load_book("vol01").dev_set, st)
    chars = [c for g in golds if g.anchored for c in g.chars]
    if not chars:
        pytest.skip("没有金标")
    conv = [c for c in chars if c.conversion]
    assert conv, "一条转换都没有——shape/reading 恐怕填成同一个值了"
    for c in conv:
        assert c.shape != c.reading
    # 转换是少数派：多数字位两者相同
    assert len(conv) < len(chars) * 0.1, \
        f"转换 {len(conv)}/{len(chars)} 太多，八成是对齐错位"


@needs
def test_no_wrong_admission_against_the_gold():
    """自动进库的字必须与金标**字形**一致——零容忍。

    进库进的是字形（GlyphDB 存的是刻本上实际刻的形），所以比 shape 不比
    reading。实测修 near_form 之前唯一的错是 vol01:151:8:4 把「論」认成
    「諭」（库候选 0.9923 vs 0.9898 只差 0.0025）。
    """
    st = ProductStore()
    bk = load_book("vol01")
    gold = {c.id: c for g in align_book("vol01", bk.dev_set, st) if g.anchored
            for c in g.chars}
    if not gold:
        pytest.skip("没有金标")
    bad: list = []
    soft: list = []          # replace 段的不符：金标自身可能错，分开看
    for pg in bk.dev_set:
        a = st.read("vol01", "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            for r in cc.chars:
                if not r.admit or not r.char:
                    continue
                g = gold.get(r.id)
                if not g or r.char == g.shape:
                    continue
                # `replace` 段的金标 shape 是**整理本给的**，不是图上认的
                # ——短 replace 段（op_run ≤ 2）正是对齐闸自己警告的高风险
                # 位置，那里金标可能就是错的。实测 vol01:21:3:21：图上清清
                # 楚楚是「身」，库 cov 1.000 也是「身」，而整理本对齐把它
                # 放成了「易」。这种位置不该算管线的错。
                #
                # 所以只对 `equal` 段零容忍（那里金标恒等于当次转写，是自证，
                # 本来就该 100%），replace 段单独收集、只在数量异常时才报。
                if g.align_op == "equal":
                    bad.append((r.id, r.char, g.shape, r.channel))
                else:
                    soft.append((r.id, r.char, g.shape, g.op_run, r.channel))
    assert not bad, f"equal 段自动进库与金标字形不符（零容忍）：{bad[:5]}"
    # replace 段：金标自身可能有误，只在成规模时报——单条多半是金标的问题
    assert len(soft) <= 3, f"replace 段不符 {len(soft)} 条，超出金标噪声量级：{soft[:5]}"


@needs
def test_near_form_families_never_auto_admit_on_shape_alone():
    """形近家族不许只凭形状证据自动进库。

    这是 C1 包壳曾经的漏洞：judge_doubts 在 v1 里靠整理本产出 near_form，
    这里没有整理本，若不自己判，admission_decision 的形近防线整条失效。
    """
    from open_guji_cv.clustering.seeding import NEAR_FORM_CHARS
    st = ProductStore()
    bk = load_book("vol01")
    for pg in bk.dev_set:
        a = st.read("vol01", "seed_admit", page_key(pg), "seed_admit")
        m = st.read("vol01", "glyph_match", page_key(pg), "glyph_match")
        if a is None or m is None:
            continue
        mm = {r.id: r for cc in m.columns for r in cc.chars}
        for cc in a.columns:
            for r in cc.chars:
                if not r.admit or r.channel not in ("match_solo", "match_solo_ocr"):
                    continue
                mr = mm.get(r.id)
                if mr is None:
                    continue
                cands = {c for c, _v in mr.candidates[:3]} | ({r.char} if r.char else set())
                assert not (cands & NEAR_FORM_CHARS), \
                    f"{r.id} 候选里有形近家族字 {cands & NEAR_FORM_CHARS} 却走了 {r.channel}"
