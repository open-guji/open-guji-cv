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
