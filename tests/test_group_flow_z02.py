# -*- coding: utf-8 -*-
"""Z02 判法打架（A24 深挖 2026-11-06）：`flow._ref_pair_pick`／`flow._dissent_keep` 两个纯函数，和五条收窄的 L1 规则。

trail 都是殿本 ★main 包里真实格的解法留痕（精简），看图定的真字写在注释里。"""
from __future__ import annotations

import re

from open_guji_cv.groups.ctx_l1 import TARGET, CtxL1Backend
from open_guji_cv.groups.flow import _dissent_keep, _ref_pair_pick, rules_path
from open_guji_cv.groups.registry import GROUPS


def canon(c):
    return {"㑹": "會", "㓂": "寇"}.get(c, c)


def T(solver, char, margin=None, **kw):
    return {"solver": solver, "char": char, "margin": margin, **kw}


# —— ref_pair：整理本字＝本组解法给的字，反对的只有图像路 ——

def test_ref_pair_ctx_and_ref_beat_image():
    # vol44:10:5:21「爲十[二]卷題日新書」库首位 一，整理本 二、文意 二；字形 ids／yr_bars 在切残的格上判一（看图：二）
    trail = [T("ctx", "二", via="ctx:ctx_llm"), T("ids", "一", 1.0759), T("yr_bars", "一")]
    assert _ref_pair_pick("yr", trail, "二", canon, 1.5) == "二"


def test_ref_pair_joint_partner_abstains():
    # vol08:35:1:17「至[于]大別」放行字 千，整理本 于、文意 于；搭档 yz 没有裁定（cache_miss）→ 联合判卡住
    trail = [T("ctx", "于"), T("ids", None), T("yz:ctx", None, why="cache_miss")]
    assert _ref_pair_pick("zy", trail, "于", canon, 1.5) == "于"


def test_ref_pair_blocked_when_text_dissents():
    # 文意给了别字（搭档文意给 問）不取
    trail = [T("ids", "閣", 1.17), T("wj:ctx", "問"), T("wj:ids", None)]
    assert _ref_pair_pick("men", trail, "閣", canon, 1.5) is None


def test_ref_pair_blocked_by_codepoint():
    # 码位解法给别字（vol38:182:8:15 山，码表给 出）不取
    trail = [T("ids", "山", 1.2868), T("chu:codepoint", "出")]
    assert _ref_pair_pick("sy", trail, "山", canon, 1.5) is None


def test_ref_pair_strong_image_dissent_blocked():
    trail = [T("ctx", "二"), T("ids", "一", 1.9)]
    assert _ref_pair_pick("yr", trail, "二", canon, 1.5) is None


def test_ref_pair_no_ctx_needs_weaker_dissent():
    # 没有文意支持：支持的 ids（0.70）弱于反对的图像路（0.9）不取；强于才取
    assert _ref_pair_pick("men", [T("ids", "闕", 0.70), T("wj:ids", "闢", 0.9)], "闕", canon, 1.5) is None
    assert _ref_pair_pick("men", [T("ids", "闕", 0.70), T("wj:ids", "闢", 0.4)], "闕", canon, 1.5) == "闕"


def test_ref_pair_needs_ref_member_and_supporter():
    assert _ref_pair_pick("yr", [T("ctx", "二")], None, canon, 1.5) is None
    assert _ref_pair_pick("yr", [T("ctx", "二")], "〓", canon, 1.5) is None
    assert _ref_pair_pick("yr", [T("ctx", "一")], "二", canon, 1.5) is None       # 本组没人给整理本的字
    assert _ref_pair_pick("yr", [T("ctx", "二")], "人", canon, 1.5) is None       # 整理本字不是组员


def test_ref_pair_keeps_solver_form():
    # 整理本 㓂、文意 寇：取解法给的字形，不改写成整理本形（码位归一同字）
    trail = [T("ctx", "寇"), T("form:canon", "㓂")]
    assert _ref_pair_pick("kgc", trail, "㓂", canon, 1.5) == "寇"


# —— dissent_keep：整理本＝放行字，只有弱图像票反对 ——

def test_dissent_keep_ids_weak():
    # vol15:24:2:6「疑[而]疑者」放行 而＝整理本，文意 而，ids 判 面（0.60，看图 而）
    assert _dissent_keep("em", [T("ctx", "而"), T("ids", "面", 0.6031)], "而", "而", canon, 1.0)


def test_dissent_keep_ids_margin_cap():
    assert not _dissent_keep("em", [T("ctx", "而"), T("ids", "面", 1.2)], "而", "而", canon, 1.0)


def test_dissent_keep_yr_bars():
    # 殿本 一二 切残的格数横必错：yr_bars 判 二 反对文意＋ids 的 一（看图 一）
    assert _dissent_keep("yr", [T("ctx", "一"), T("ids", "一", 0.9358), T("yr_bars", "二")], "一", "一", canon, 1.0)


def test_dissent_keep_text_dissent_stays():
    # 文意规则给别字：照旧降审（规则误判由 rules.yaml 收窄，不在这里放过）
    assert not _dissent_keep("yt", [T("ctx", "圖", via="ctx:ctx_l1"), T("ids", "圓", 0.6299)], "圓", "圓", canon, 1.0)


def test_dissent_keep_needs_ref_equal_and_supporter():
    assert not _dissent_keep("em", [T("ctx", "而"), T("ids", "面", 0.6)], "而", "面", canon, 1.0)
    assert not _dissent_keep("em", [T("ctx", None), T("ids", "面", 0.6)], "而", "而", canon, 1.0)   # 没有解法支持放行字
    assert not _dissent_keep("em", [T("ctx", "而"), T("ids", "面", 0.6)], "而", None, canon, 1.0)


# —— 收窄的 L1 规则：误判例不再命中，原命中例照旧 ——

def _fires(g: str, rid: str, left: str, right: str) -> bool:
    ru = {r.id: r for r in CtxL1Backend(rules_path(g), GROUPS[g].members).rules}[rid]
    return bool(ru.pattern.search(left + TARGET + right))


def test_rule_zh_zengjing_excludes_fuhui():
    assert not _fires("zh", "zh-曾經", "子以爲理", "經義以鉗")     # 理會經義（會）
    assert not _fires("zh", "zh-曾經", "擊於是附", "經義以鉗")     # 附會經義（會）
    assert _fires("zh", "zh-曾經", "其書", "經頗得")               # 曾經（曾）照旧


def test_rule_js_shen_excludes_jia_words():
    assert not _fires("js", "js-申-l1", "圍鄭左傳", "午晉侯")       # 傳甲午
    assert not _fires("js", "js-申-l1", "諸書所引", "帳珠簾")       # 引甲帳
    assert _fires("js", "js-申-l1", "庚", "以後")                  # 庚申


def test_rule_yh_yt_rm_narrowed():
    assert not _fires("yh", "yh-遺文", "禁僧俗往", "詔修整街")      # 往還詔（還）
    assert not _fires("yh", "yh-還朝", "補", "原目本一")            # 補遺原目（遺）
    assert not _fires("yt", "yt-圓", "太極", "形以黑白")            # 圖形（圖）
    assert not _fires("rm", "rm-日", "每", "之中又各")              # 每目之中（目）
    assert not _fires("yh", "yh-還朝", "公矣論張浚者往往", "議於朱子")   # 往往遺議（遺）
    assert not _fires("yt", "yt-圖", "韻而成是地", "篇稱呼音")         # 地圓篇（圓）
    assert not _fires("yt", "yt-圖", "與宰相崔", "書請先防")           # 崔圓（人名）
    assert _fires("yt", "yt-圖", "卷首河", "說二篇")                  # 河圖說照旧
    assert _fires("yh", "yh-遺文", "補", "文")                      # 補遺文照旧
    assert _fires("yh", "yh-還朝", "召", "")


# —— dissent_l1：L1 规则孤证反对，整理本×ids 同意放行字（vol66:44:9:18 曾試宏詞，看图＝曾）——

def test_dissent_keep_l1_alone_needs_ids_support():
    trail = [T("ctx", "會", via="ctx:ctx_l1"), T("ids", "曾", 0.4)]
    assert not _dissent_keep("zh", trail, "曾", "曾", canon, 1.0)                  # 缺省不认 L1 弱票
    assert _dissent_keep("zh", trail, "曾", "曾", canon, 1.0, l1_weak=True)
    assert not _dissent_keep("zh", [T("ctx", "會", via="ctx:ctx_l1")], "曾", "曾", canon, 1.0, l1_weak=True)   # 没有 ids 同意
    assert not _dissent_keep("zh", [T("ctx", "會", via="ctx:ctx_llm"), T("ids", "曾", 0.4)], "曾", "曾", canon, 1.0, l1_weak=True)  # 大模型文意照旧降审


# —— ctx_agree：入人八 rr 要整理本×文意一致才放（vol11:88:1:16 入、vol51:53:9:18 人）——

def test_ctx_agrees_helper():
    from open_guji_cv.groups.flow import _ctx_agrees
    trail = [T("ctx", "入", via="ctx:ctx_llm"), T("rr_img", "人", 0.3), T("ids", "入", 0.5), T("wj:ctx", "人")]
    assert _ctx_agrees(trail, "入", canon)
    assert not _ctx_agrees(trail, "人", canon)                              # 搭档文意不算
    assert not _ctx_agrees([T("rr_img", "入"), T("ids", "入", 0.5)], "入", canon)   # 没有文意
