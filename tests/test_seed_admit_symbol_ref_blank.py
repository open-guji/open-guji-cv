# -*- coding: utf-8 -*-
"""Step7 圈号 ○ 遇整理本空格位（`symbol_ref_blank`，通道 `symbol_ref_blank`）。直接测 `_symbol_ref_blank_pass`，数据自造。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _symbol_ref_blank_pass

B = "tbook:1"


def _run(cells, lib, coord, **params):
    p = SeedAdmitParams(db_path="x", symbol_ref_blank="○", **params)
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c.get("admit", False), char=c.get("char"),
                     doubts=list(c.get("doubts", [])), channel=c.get("channel"),
                     provenance=c.get("provenance", ""), evidence=c.get("evidence") or {})
            for s, c in cells.items()]
    mm = {f"{B}:1:{s}": NS(char=None, candidates=v, verdict="unsure", guard=None) for s, v in lib.items()}
    n = _symbol_ref_blank_pass(p, [ColumnAdmit(col=1, chars=recs)], mm, {f"{B}:1:{s}": c for s, c in coord.items()})
    return n, {r.slot: r for r in recs}


def test_admits_circle_on_blank_ref():
    n, r = _run({1: {"char": "○", "doubts": ["symbol"], "evidence": {"symbol": "○"}}},
                {1: [("○", 0.99), ("口", 0.9)]}, {1: ""})
    assert n == 1
    assert (r[1].admit, r[1].channel, r[1].char, r[1].provenance) == (True, "symbol_ref_blank", "○", "match")
    assert r[1].doubts == ["lane_symbol_ref_blank"] and "symbol" not in r[1].evidence


def test_demoted_symbol_records_demoted_from():
    n, r = _run({1: {"admit": True, "char": "○", "channel": "match_solo"}}, {1: [("○", 0.99)]}, {1: ""})
    assert n == 1 and r[1].evidence["demoted_from"] == {"channel": "match_solo", "by": "symbol_ref_blank"}


def test_leaves_alone():
    cells = {1: {"char": "○"}, 2: {"char": "○"}, 3: {"char": "○", "doubts": ["occluded"]},
             4: {"char": "○", "evidence": {"occluded": {"via": "coord"}}}, 5: {"char": "口"},
             6: {"char": "○", "admit": True, "channel": "human", "provenance": "human"}, 7: {"char": "○"}}
    lib = {i: [("○", 0.99)] for i in cells}
    lib[2] = [("○", 0.95)]       # cov 不够
    lib[5] = [("○", 0.99)]       # 机器字不是名单里的符号
    n, r = _run(cells, lib, {1: "日", 2: "", 3: "", 4: "", 5: "", 6: "", 7: None} | {})  # 1 整理本有字；7 对位没给
    assert n == 0 and not any(x.admit for k, x in r.items() if k != 6)


def test_off_by_default_and_not_in_dump():
    assert "symbol_ref_blank" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", symbol_ref_blank="○").model_dump()["symbol_ref_blank_cov"] == 0.97
