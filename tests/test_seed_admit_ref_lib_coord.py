# -*- coding: utf-8 -*-
"""`seed_admit.ref_lib_coord`（史記 2026-11-01，书级、缺省关）：坐标对位的整理本字＝库首位＝本格字 → 按整理本放行。判据纯函数。"""
from __future__ import annotations

from open_guji_cv.steps.seed_admit import SeedAdmitParams, ref_lib_coord_decide

SEM = lambda c: {"傳": "傳", "𫝊": "傳", "會": "會", "㑹": "會"}.get(c, c)


def dec(**kw):
    base = dict(char="𫝊", ref="𫝊", cands=[("𫝊", 0.959), ("傳", 0.9539), ("傅", 0.9524)], verdict="unsure", guard=None,
                doubts=["库 unsure(cov=0.959)", "上下文 margin 不足(0.69)"], evidence={}, semantic=SEM, cov_min=0.90, gap_min=0.005)
    base.update(kw)
    return ref_lib_coord_decide(**base)


def test_reference_trust_levels_and_dump():
    assert SeedAdmitParams().reference_trust == "none"
    assert "reference_trust" not in SeedAdmitParams().model_dump()
    off, hi, vh = (SeedAdmitParams(reference_trust=t) for t in ("none", "high", "very_high"))
    assert off._rt_rank() == 0 and not off._rt_shape_ref_ok() and not off._rt_abstain_ref_ok() and not off._follow_variants()
    assert hi._rt_rank() == 1 and "guang" in hi._rt_shape_ref_ok() and {"jys", "zh"} <= hi._rt_abstain_ref_ok()
    assert "ry" in hi._rt_lift_shape_ref() and hi._follow_variants()
    assert vh._rt_rank() == 2
    assert vh.model_dump()["reference_trust"] == "very_high"
    # 旧开关仍可单独写，取并集
    assert "别" not in SeedAdmitParams(group_flow_abstain_ref_ok=["bie"])._rt_abstain_ref_ok()
    assert "bie" in SeedAdmitParams(group_flow_abstain_ref_ok=["bie"], reference_trust="high")._rt_abstain_ref_ok()


def test_basic_admit_and_rival_gap():
    assert dec()                                                                   # 傳＝𫝊 同义，傅 差 0.0066 ≥ gap
    assert not dec(cands=[("𫝊", 0.959), ("傅", 0.9575)])                          # 语义不同的对手紧咬
    assert not dec(cands=[("𫝊", 0.85)])                                           # cov 不够
    assert not dec(cands=[("傳", 0.97), ("𫝊", 0.9)])                              # 库首位不是整理本字（无 blind）
    assert not dec(char="傳")                                                      # 字≠整理本字
    assert not dec(guard="never_match") and not dec(verdict="diff")


def test_doubt_whitelist_and_skip_chars():
    assert not dec(doubts=["库 unsure(cov=0.959)", "occluded_x"])                  # 白名单外的疑问不碰
    assert not dec(doubts=["group_flow_disagree"])
    assert not dec(char="曰", ref="曰", cands=[("曰", 0.98)])                      # 日曰不碰
    assert dec(doubts=["库 unsure(cov=0.959)", "group_flow_abstain"])


def test_human_unbound_and_group_solvers():
    assert dec(evidence={"human_unbound": {"char": "𫝊"}})                          # 旧人裁字＝放行字
    assert not dec(evidence={"human_unbound": {"char": "傅"}})
    ev = lambda *ts, g="zh": {"group": {"id": g, "solvers": [dict(solver=s, char=c) for s, c in ts]}}
    assert dec(char="㑹", ref="㑹", cands=[("㑹", 0.97)], evidence=ev(("ids", "會")))   # ids 给同义异体：放
    assert not dec(char="㑹", ref="㑹", cands=[("㑹", 0.97)], evidence=ev(("ctx", "曾")))  # 文意给别的字：不放
    assert not dec(char="廣", ref="廣", cands=[("廣", 0.97)], evidence=ev(("ids", "賔"), g="guang"))
    assert dec(char="廣", ref="廣", cands=[("廣", 0.97)], evidence=ev(("ids", "賔"), g="guang"), shape_ok=frozenset({"guang"}))


def test_blind_needs_ctx_guard_ref_and_healthy_column():
    kw = dict(char="省", ref="省", cands=[("者", 0.9402), ("省", 0.9366)], doubts=["库 unsure(cov=0.940)", "ctx_guard_ref"])
    assert not dec(**kw)
    assert dec(**kw, blind_ok=True)
    assert not dec(**{**kw, "doubts": ["库 unsure(cov=0.940)"]}, blind_ok=True)    # 没有 ctx_guard_ref
    assert not dec(**{**kw, "cands": [("者", 0.99), ("省", 0.9)]}, blind_ok=True)  # 库强烈说是别的字


def test_non_han_ref_and_few_stroke_guards():
    """史記 r12：参校字不是汉字（ခ）不放；少笔画字名单里库首位≠参校字的盲放不放。"""
    assert not dec(char="ခ", ref="ခ", cands=[("ခ", 0.99)])                         # 参校字缅文
    assert dec(char="𫝊", ref="𫝊")                                                  # 汉字照放
    assert dec(char="", ref="", cands=[("", 0.99)])               # 私用码造字仍算字
    blind = dict(char="下", ref="下", cands=[("十", 0.95), ("下", 0.9)], doubts=["ctx_guard_ref"], blind_ok=True)
    assert dec(**blind)                                                            # 无名单：盲放照旧
    assert not dec(**blind, few_stroke=frozenset("下十"))
    assert dec(**blind, few_stroke=frozenset("一二三"))                             # 不涉及的字不受影响
    assert "lane_coord_few_stroke" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(lane_coord_few_stroke=("一", "二")).model_dump()["lane_coord_few_stroke"] == ("一", "二")


def test_context_page_end_doubt_allowed():
    """L04（A23）：页尾格带 `context_page_end` 疑问，库首位＝整理本字时也可按整理本放（史記 3 格，殿本 0）。"""
    assert dec(doubts=["context_page_end"])
    assert dec(doubts=["库 unsure(cov=0.959)", "context_page_end"])
    assert not dec(doubts=["context_page_end", "别的疑问"])
