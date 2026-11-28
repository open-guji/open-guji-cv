# -*- coding: utf-8 -*-
"""Step7 异体边表自动暂归一（`edge_pair`，通道 `edge_pair`，open_guji_cv/edge_pairs.py）：数据全是自造的。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from open_guji_cv.groups import edge_pairs
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _edge_pair_pass

B = "tbook:1"


def _page(cells):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c.get("admit", False), char=c.get("char"),
                     doubts=list(c.get("doubts", [])), channel=c.get("channel"),
                     provenance=c.get("provenance", "")) for s, c in cells.items()]
    return [ColumnAdmit(col=1, chars=recs)]


def _mm(lib):
    out = {}
    for s, v in lib.items():
        cands, verdict, guard = (list(v) + [None, None])[:3]
        out[f"{B}:1:{s}"] = NS(char=None, candidates=cands, verdict=verdict or "unsure", guard=guard)
    return out


def _run(cells, lib, coord, ctx=None, **params):
    p = SeedAdmitParams(db_path="x", **params)
    out = _page(cells)
    dmap = {f"{B}:1:{s}": NS(char=c) for s, c in (ctx or {}).items()}
    n = _edge_pair_pass(p, out, _mm(lib), {}, {f"{B}:1:{s}": c for s, c in coord.items()}, dmap)
    return n, {r.slot: r for r in out[0].chars}


def test_auto_pair_rule():
    assert edge_pairs.is_auto_pair("㛰", "婚") and edge_pairs.is_auto_pair("婚", "㛰")
    assert edge_pairs.is_auto_pair("彥", "彦")
    assert not edge_pairs.is_auto_pair("鍾", "鐘")      # T2 互通，不是同词
    assert not edge_pairs.is_auto_pair("已", "巳")      # 字组成员／排除表
    assert not edge_pairs.is_auto_pair("手", "扌")      # 排除表
    assert not edge_pairs.is_auto_pair("書", "畫")      # 无边
    assert not edge_pairs.is_auto_pair("兩", "雨")
    assert not edge_pairs.is_auto_pair("寶", "寳")      # 已在字组（cp_bao3）里，字组自己判


def test_pair_to_prefers_common_form():
    assert edge_pairs.pair_to("㛰", "婚") == "婚"
    assert edge_pairs.pair_to("祿", "禄") == "祿"
    assert edge_pairs.pair_to("㨿", "據", lib_top="㨿") in ("據", "㨿")


def test_admits_common_form_and_marks_provisional():
    n, r = _run({1: {}}, {1: ([("婚", 0.96), ("昏", 0.90)],)}, {1: "㛰"})
    assert n == 1
    assert (r[1].admit, r[1].channel, r[1].provenance, r[1].char) == (True, "edge_pair", "match", "婚")
    assert r[1].evidence["edge_pair"] == {"decision": "provisional", "pair": ["㛰", "婚"], "to": "婚"}
    assert r[1].doubts == ["lane_edge_pair"]


def test_ref_is_common_form_top_is_rare():
    """库首位是少见形、整理本是常见形 → 放常见形。"""
    n, r = _run({1: {}}, {1: ([("㛰", 0.95), ("昏", 0.90)],)}, {1: "婚"})
    assert n == 1 and r[1].char == "婚"


@pytest.mark.parametrize("lib,why", [
    ([("婚", 0.90), ("昏", 0.80)], "cov 不够"),
    ([("婚", 0.93), ("昏", 0.93)], "领先不够"),
    ([("昏", 0.96), ("婚", 0.90)], "首位不在对里"),
])
def test_no_admit(lib, why):
    n, r = _run({1: {}}, {1: (lib,)}, {1: "㛰"})
    assert n == 0 and not r[1].admit, why


def test_diff_verdict_and_guard_block():
    n, r = _run({1: {}, 2: {}}, {1: ([("婚", 0.96)], "diff"), 2: ([("婚", 0.96)], "unsure", "conflict")}, {1: "㛰", 2: "㛰"})
    assert n == 0


def test_not_variant_pair_untouched():
    n, r = _run({1: {}}, {1: ([("畫", 0.97)],)}, {1: "書"})
    assert n == 0


def test_human_and_admitted_untouched():
    n, r = _run({1: {"provenance": "human", "channel": "human"}, 2: {"admit": True, "char": "婚", "channel": "match"}},
                {1: ([("婚", 0.96)],), 2: ([("婚", 0.96)],)}, {1: "㛰", 2: "㛰"})
    assert n == 0 and r[2].char == "婚"


def test_switch_off_param():
    assert SeedAdmitParams(db_path="x").edge_pair is True
    d = SeedAdmitParams(db_path="x").model_dump() if hasattr(SeedAdmitParams, "model_dump") else None


def test_variant_edge_single_caliber():
    """放行与归因共用的异体口径（A24 V01 深挖 11-06）：T3 有边但不算异体；is_pure 才是 edge_pair 要的严口径。"""
    from open_guji_cv.variants import are_variants, variant_edge
    e = variant_edge("鼔", "鼓")
    assert e.tier == "T1" and e.is_variant and e.is_pure and e.has_edge
    t3 = variant_edge("籍", "藉")                       # 只有通假来源
    assert t3.has_edge and t3.never_only and not t3.is_variant and not t3.is_pure
    assert variant_edge("甲", "乙").tier is None
    for a, b in (("鼔", "鼓"), ("籍", "藉"), ("兩", "雨")):
        assert variant_edge(a, b).has_edge == are_variants(a, b)


def test_group_seam_variant_group():
    """字组缝：衞衛 是 weiw（异体组）组员，is_auto_pair 不认；格没进组 → edge_pair 仍放（A24 V01 深挖 11-06）。"""
    assert not edge_pairs.is_auto_pair("衞", "衛") and edge_pairs.seam_pair("衞", "衛") == "variant"
    n, r = _run({1: {}}, {1: ([("衛", 0.97), ("術", 0.956)],)}, {1: "衞"})
    assert n == 1 and r[1].admit and r[1].evidence["edge_pair"]["seam"] == "variant"
    n, r = _run({1: {}}, {1: ([("衛", 0.97), ("術", 0.956)],)}, {1: "衞"}, edge_pair_group_seam=False)
    assert n == 0


def test_group_seam_skips_cells_the_group_touched():
    p = SeedAdmitParams(db_path="x")
    out = _page({1: {}})
    out[0].chars[0].evidence = {"group": {"id": "weiw", "decision": "abstain"}}
    n = _edge_pair_pass(p, out, _mm({1: ([("衛", 0.97), ("術", 0.956)],)}), {}, {f"{B}:1:1": "衞"}, {})
    assert n == 0


def test_group_seam_near_form_needs_bigger_lead():
    """一字在形近组（迫∈chuo）：领先要 ≥0.03。"""
    assert edge_pairs.seam_pair("廹", "迫") == "near_form"
    n, _ = _run({1: {}}, {1: ([("迫", 0.948), ("廻", 0.941)],)}, {1: "廹"})
    assert n == 0
    n, r = _run({1: {}}, {1: ([("迫", 0.97), ("廻", 0.93)],)}, {1: "廹"})
    assert n == 1


def test_group_seam_never_for_weak_or_non_variant_edges():
    assert edge_pairs.seam_pair("傳", "傅") is None         # 同组形近，不是异体
    assert edge_pairs.seam_pair("徃", "往") is None         # T2，归白名单


@pytest.mark.parametrize("to,ref,lib,want,dec", [
    ("lib", "婚", "㛰", "㛰", "keben"),     # 按刻形转写的书（殿本）：放库首位，不写暂归一
    ("ref", "㛰", "婚", "㛰", "ref"),       # 按整理本录的书（史記、全唐文）：放整理本字
    ("freq", "婚", "㛰", "婚", "provisional"),
])
def test_edge_pair_to(to, ref, lib, want, dec):
    """`edge_pair_to`（A24 V01 定案 11-09）：同字只表示可以不人审，放哪一形按书定。"""
    n, r = _run({1: {}}, {1: ([(lib, 0.96), ("昏", 0.90)],)}, {1: ref}, edge_pair_to=to)
    assert n == 1 and r[1].char == want
    assert r[1].evidence["edge_pair"]["decision"] == dec


def test_edge_pair_to_default_not_dumped():
    d = SeedAdmitParams(db_path="x").model_dump()
    assert "edge_pair_to" not in d
    assert SeedAdmitParams(db_path="x", edge_pair_to="lib").model_dump()["edge_pair_to"] == "lib"
