# -*- coding: utf-8 -*-
"""p_ref_admit：P 类（机器字≠整理本、都不在字组、非半格、同列无相邻同类格）取整理本字。数据自造。"""
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _p_ref_pass

B = "tbook:1"


def _run(cells, amap, on=True):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=int("".join(ch for ch in s if ch.isdigit())), admit=c.get("admit", False), char=c.get("char"),
                     doubts=list(c.get("doubts", [])), channel=c.get("channel"), provenance=c.get("provenance", ""), evidence=c.get("ev") or {})
            for s, c in cells.items()]
    n = _p_ref_pass(SeedAdmitParams(db_path="x", p_ref_admit=on), [ColumnAdmit(col=1, chars=recs)], {f"{B}:1:{s}": (v, None) for s, v in amap.items()})
    return n, {r.id.split(":")[-1]: r for r in recs}


def test_admits_isolated_p_cell():
    n, r = _run({"1": {"admit": True, "char": "甲"}, "2": {"char": "機"}, "3": {"admit": True, "char": "乙"}}, {"1": "甲", "2": "整", "3": "乙"})
    assert n == 1 and (r["2"].admit, r["2"].char, r["2"].channel) == (True, "整", "p_ref")


def test_leaves_alone():
    ok = {"admit": True, "char": "甲"}
    assert _run({"1": ok, "2": {"char": "機"}, "3": {"char": "誤"}}, {"2": "整", "3": "正"})[0] == 0          # 相邻成片
    assert _run({"1": ok, "2a": {"char": "機"}}, {"2a": "整"})[0] == 0                                        # 半格
    assert _run({"1": ok, "2": {"char": "機", "doubts": ["occluded"]}}, {"2": "整"})[0] == 0
    assert _run({"1": ok, "2": {"char": "機", "provenance": "human", "channel": "human"}}, {"2": "整"})[0] == 0
    assert _run({"1": ok, "2": {"char": "日"}}, {"2": "整"})[0] == 0                                          # 机器字在字组（日曰）
    assert _run({"1": ok, "2": {"char": "機", "ev": {"group": {"id": "ry"}}}}, {"2": "整"})[0] == 0           # 字组格
    assert _run({"1": ok, "2": {"char": "整"}}, {"2": "整"})[0] == 0                                          # 机器字=整理本
    assert "p_ref_admit" not in SeedAdmitParams(db_path="x").model_dump()
