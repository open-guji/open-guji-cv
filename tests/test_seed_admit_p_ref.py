# -*- coding: utf-8 -*-
"""p_ref_admit：P 类（机器字≠整理本、都不在字组、非半格、同列无相邻同类格）取整理本字。数据自造。"""
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _p_ref_pass

B = "tbook:1"


def _run(cells, amap, on=True, **kw):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=int("".join(ch for ch in s if ch.isdigit())), admit=c.get("admit", False), char=c.get("char"),
                     doubts=list(c.get("doubts", [])), channel=c.get("channel"), provenance=c.get("provenance", ""), evidence=c.get("ev") or {})
            for s, c in cells.items()]
    n = _p_ref_pass(SeedAdmitParams(db_path="x", p_ref_admit=on, **kw), [ColumnAdmit(col=1, chars=recs)], {f"{B}:1:{s}": (v, None) for s, v in amap.items()})
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


def test_max_cov_only_below_ceiling():
    """p_ref_max_cov：机器字库覆盖率 ≥ 上限（库认得机器字）不放；缺 cov 不放；None＝不核。"""
    ok = {"admit": True, "char": "甲"}
    cells = lambda cov: {"1": ok, "2": {"char": "機", "ev": {"cov": cov} if cov is not None else {}}}   # noqa: E731
    assert _run(cells(0.90), {"2": "整"}, p_ref_max_cov=0.93)[0] == 1
    assert _run(cells(0.95), {"2": "整"}, p_ref_max_cov=0.93)[0] == 0
    assert _run(cells(0.93), {"2": "整"}, p_ref_max_cov=0.93)[0] == 0          # 严格小于
    assert _run(cells(None), {"2": "整"}, p_ref_max_cov=0.93)[0] == 0
    assert _run(cells(0.99), {"2": "整"})[0] == 1                               # 缺省不核
    n, r = _run(cells(0.90), {"2": "整"}, p_ref_max_cov=0.93)
    assert r["2"].evidence["p_ref"]["cov"] == 0.90


def test_adjacent_and_jiazhu_switches():
    ok = {"admit": True, "char": "甲"}
    adj = {"1": ok, "2": {"char": "機"}, "3": {"char": "誤"}}
    assert _run(adj, {"2": "整", "3": "正"})[0] == 0
    assert _run(adj, {"2": "整", "3": "正"}, p_ref_adjacent=True)[0] == 2        # 放开成片
    half = {"1": ok, "2a": {"char": "機"}}
    assert _run(half, {"2a": "整"})[0] == 0
    assert _run(half, {"2a": "整"}, p_ref_jiazhu=True)[0] == 1                    # 放开夹注半格
    # 相邻判断不含 cov：旁边那格 cov 高也算成片，除非放开相邻
    mix = {"1": ok, "2": {"char": "機", "ev": {"cov": 0.90}}, "3": {"char": "誤", "ev": {"cov": 0.99}}}
    assert _run(mix, {"2": "整", "3": "正"}, p_ref_max_cov=0.93)[0] == 0
    assert _run(mix, {"2": "整", "3": "正"}, p_ref_max_cov=0.93, p_ref_adjacent=True)[0] == 1


def test_knobs_not_in_dump_when_default():
    d = SeedAdmitParams(db_path="x").model_dump()
    assert not {"p_ref_max_cov", "p_ref_adjacent", "p_ref_jiazhu"} & set(d)
    d = SeedAdmitParams(db_path="x", p_ref_admit=True).model_dump()
    assert "p_ref_admit" in d and not {"p_ref_max_cov", "p_ref_adjacent", "p_ref_jiazhu"} & set(d)
    d = SeedAdmitParams(db_path="x", p_ref_admit=True, p_ref_max_cov=0.93, p_ref_jiazhu=True).model_dump()
    assert d["p_ref_max_cov"] == 0.93 and d["p_ref_jiazhu"] is True and "p_ref_adjacent" not in d
