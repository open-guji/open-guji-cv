# -*- coding: utf-8 -*-
"""v2 × 整理本自动金标 + C1 的 near_form 防线。"""

from __future__ import annotations

from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.workspace import raw_root
from open_guji_cv.gold.v2_align import DEFAULT_CORPUS as GOLD_CORPUS
from open_guji_cv.gold.v2_align import align_book
from open_guji_cv.products.store import ProductStore

REPO = Path(__file__).resolve().parent.parent


def _ws_raw():
    """原图根：优先 GUJI_WORKSPACE（数据已迁 siku-zongmu-workspace），
    没设则退回仓根——引擎自带的小样本仍在仓内。"""
    return raw_root()
RAW = _ws_raw() / "data_full" / "zongmu"
# ⚠️ 跳过判据要查的是 `align_book` **真正会读**的那份语料，不是随便一份整理本。
# 2026-09-13 订正：这里原本查 `zongmu_wuyingdian_reference.txt`（武英殿本，仍在
# 现役，但那是字表/字形/训练那批脚本用的），而 `gold.v2_align.DEFAULT_CORPUS`
# 走的是 `zongmu_wenyuange_wikisource.txt`（文渊阁本）——查 A 跑 B，A 在 B 不在
# 时就会跑进来然后锚不上。
#
# 更要命的是**同名语料有两份**：仓内 `corpus/` 那份只有 17KB（样本，够跑单元
# 测试），工作区那份 8.2MB（真语料），差 470 倍。`core.workspace` 专门有个
# `using_sample_corpus()` 就是为这个坑设的。于是：
#   什么都不设            → 样本语料 + 仓内产物 → 8-gram 锚定失败，本条 skip
#   export GUJI_WORKSPACE → 真语料 + 工作区产物 + 工作区 cache → 锚上 12/12
# 要真跑它就**只设 GUJI_WORKSPACE**，让 corpus / products / cache 三者配套指向
# 工作区。⚠️ 别再额外设 `GUJI_PRODUCTS_DIR` 去钉产物：vol01 的 23472 个字块缓存
# 只在工作区，把 products 单独指回仓内会让 products 与 cache 分家，
# test_rulers / test_v1_bridge / test_font_candidates 那批读图块的会整片报
# 「分母为 0」「0/179 个 char 实例落了图块」——那是环境拆错了，不是算法坏了。
# 两种环境都不会报假绿：锚不上就 skip，不会假装通过。
CORPUS = Path(GOLD_CORPUS)
needs = pytest.mark.skipif(not (RAW.exists() and CORPUS.exists()),
                           reason="需要原图与整理本（GOLD_CORPUS 指的那份）")


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
                # 人裁通道（seed_admit v1.4）：人看着图判的字形是最强证据，
                # 金标的 shape 只是**当次转写**，两者不同时该以人裁为准，不算错。
                # 实例 vol01:151:9:20——人裁字形「巳」、释读「已」（己已巳 三字
                # 字形与文意分岔，设计如此），而 context 通道当次转写成了「已」。
                if r.channel == "human":
                    continue
                # `source == "fallback"`：Step6 **弃权**的位，`shape` 是
                # `slots_from_decision` 逐级兜底（库 kNN top1 → OCR top1）填的
                # **对齐载体**，不是"管线认为这一位是什么字"。该函数 docstring
                # 自己写着「兜底字只是对齐载体…所以兜底字错了也不会污染
                # `align_char`」——既然声明了它可能是错的，就不能拿它当零容忍
                # 金标。实例 vol01:26:5:-1：Step6 char=None（margin 0.0126，
                # source=prior，排序 正 0.395 / 玉 0.383 / 世 0.222），兜底取了
                # 库 top1「正」写进 shape；而该列读作「世祖章皇帝曾降…」，
                # slot=-1 正是避讳抬头位，文意与格式都锁死了是「世」。
                # dev_set 1930 个金标位里 84 位是 fallback，都属此类。
                if g.source == "fallback":
                    continue
                # 异体字对上 Step6 的 LM 微弱打分差：`shape` 取的是 Step6 定字，
                # 而 Step6 在异体字上靠上下文模型打分，两个形分数常常只差几个点
                # ——这个量级分不出「刻本上刻的是哪个形」，但 `align_char`（8-gram
                # 锚定后与整理本原文逐字比对）分得出。实例 vol01:141:7:2 与
                # vol01:11:4:21：Step6 排序「旨 0.52 / 㫖 0.46」取了旨，而整理本
                # 原文两处都作㫖——「諭㫖各註某家藏本」「撮取著書大㫖」，且都是
                # op=equal 严丝合缝对齐；文渊阁本全书用㫖 1292 次、用旨 684 次。
                # C1 走的正是 `_pick_char` 里「库 unsure 时整理本字是更好的字形
                # 估计」那条路（见 seed_admit.py 该函数 docstring），采信 align_char
                # 比采信 LM 打分更可信。这类位以 align_char 为准，不算管线的错。
                if g.reading and r.char == g.reading:
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
