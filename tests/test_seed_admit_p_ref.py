# -*- coding: utf-8 -*-
"""p_ref_admit：P 类（机器字≠整理本、都不在字组、非半格、同列无相邻同类格）取整理本字。数据自造。"""
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _p_ref_pass

B = "tbook:1"


def _run(cells, amap, on=True, coord=None, **kw):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=int("".join(ch for ch in s if ch.isdigit())), admit=c.get("admit", False), char=c.get("char"),
                     doubts=list(c.get("doubts", [])), channel=c.get("channel"), provenance=c.get("provenance", ""), evidence=c.get("ev") or {})
            for s, c in cells.items()]
    n = _p_ref_pass(SeedAdmitParams(db_path="x", p_ref_admit=on, **kw), [ColumnAdmit(col=1, chars=recs)], {f"{B}:1:{s}": (v, None) for s, v in amap.items()},
                     {f"{B}:1:{s}": v for s, v in coord.items()} if coord is not None else None)
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


def test_p_ref_coord_takes_coord_ref_only_when_no_text_label():
    """p_ref_coord（P02）：文本对位没标签的格退到坐标对位字；有文本标签的以文本为准；非 coord 调用方不受影响。"""
    ok = {"admit": True, "char": "甲"}
    cells = {"1": ok, "2": {"char": "機", "ev": {"cov": 0.90}}, "3": ok}
    assert _run(cells, {}, coord={"2": "整"})[0] == 1
    n, r = _run(cells, {}, coord={"2": "整"})
    assert (r["2"].char, r["2"].evidence["p_ref"]["via"]) == ("整", "coord")
    assert _run(cells, {}, coord=None)[0] == 0                                           # 没给 coord 等于关
    n, r = _run(cells, {"2": "文"}, coord={"2": "整"})
    assert r["2"].char == "文" and r["2"].evidence["p_ref"]["via"] == "align"           # 文本对位优先
    assert _run(cells, {}, coord={"2": "整"}, p_ref_max_cov=0.85)[0] == 0                 # cov 旋钮同管
    assert _run({"1": ok, "2": {"char": "機"}, "3": {"char": "誤"}}, {}, coord={"2": "整", "3": "正"})[0] == 0   # 相邻成片照拦


def test_p_ref_coord_knob_not_in_dump_when_default():
    d = SeedAdmitParams(db_path="x", p_ref_admit=True).model_dump()
    assert "p_ref_coord" not in d
    assert SeedAdmitParams(db_path="x", p_ref_admit=True, p_ref_coord=True).model_dump()["p_ref_coord"] is True
    assert "p_ref_coord" not in SeedAdmitParams(db_path="x", p_ref_coord=True).model_dump()


def test_skip_variant_guard():
    """p_ref_skip_variant：机器字与整理本字有直接异体边（羨／羡）不取整理本字；非异体照放。"""
    ok = {"admit": True, "char": "甲"}
    assert _run({"1": ok, "2": {"char": "羡"}}, {"2": "羨"})[0] == 1
    assert _run({"1": ok, "2": {"char": "羡"}}, {"2": "羨"}, p_ref_skip_variant=True)[0] == 0
    assert _run({"1": ok, "2": {"char": "機"}}, {"2": "整"}, p_ref_skip_variant=True)[0] == 1
    d = SeedAdmitParams(db_path="x", p_ref_admit=True).model_dump()
    assert "p_ref_skip_variant" not in d


def test_coord_own_knobs_independent_of_p01_knobs():
    """1.50：坐标对位格用自己的 cov 上限与相邻开关；P01（文本对位）格仍按 p_ref_max_cov／p_ref_adjacent。"""
    ok = {"admit": True, "char": "甲"}
    two = {"1": ok, "2": {"char": "機", "ev": {"cov": 0.90}}, "3": {"char": "誤", "ev": {"cov": 0.90}}}
    # P01 开相邻：文本对位的相邻格照放；坐标对位的相邻格仍拦
    assert _run(two, {"2": "整", "3": "正"}, p_ref_adjacent=True)[0] == 2
    assert _run(two, {}, coord={"2": "整", "3": "正"}, p_ref_adjacent=True)[0] == 0
    assert _run(two, {}, coord={"2": "整", "3": "正"}, p_ref_adjacent=True, p_ref_coord_adjacent=True)[0] == 2
    # cov 上限：coord 用自己的；None 沿用 p_ref_max_cov
    hi = {"1": ok, "2": {"char": "機", "ev": {"cov": 0.96}}}
    assert _run(hi, {"2": "整"}, p_ref_max_cov=0.97)[0] == 1
    assert _run(hi, {}, coord={"2": "整"}, p_ref_max_cov=0.97)[0] == 1                      # 沿用
    assert _run(hi, {}, coord={"2": "整"}, p_ref_max_cov=0.97, p_ref_coord_max_cov=0.94)[0] == 0
    assert _run(hi, {"2": "整"}, p_ref_max_cov=0.97, p_ref_coord_max_cov=0.94)[0] == 1      # 不影响文本对位格


def test_coord_own_knobs_not_in_dump_when_default():
    d = SeedAdmitParams(db_path="x", p_ref_admit=True, p_ref_coord=True).model_dump()
    assert not {"p_ref_coord_max_cov", "p_ref_coord_adjacent"} & set(d)
    d = SeedAdmitParams(db_path="x", p_ref_admit=True, p_ref_coord=True, p_ref_coord_max_cov=0.94).model_dump()
    assert d["p_ref_coord_max_cov"] == 0.94 and "p_ref_coord_adjacent" not in d
    assert "p_ref_coord_max_cov" not in SeedAdmitParams(db_path="x", p_ref_admit=True, p_ref_coord_max_cov=0.94).model_dump()
