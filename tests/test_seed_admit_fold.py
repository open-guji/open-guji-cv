# -*- coding: utf-8 -*-
"""fold_groups：折叠组内待审格，整理本字在组里 → 放整理本字（通道 fold）。数据自造。"""
from open_guji_cv.groups.registry import FLOW_GROUPS
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _fold_pass

B = "tbook:1"


def _run(groups, cells, amap):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=1, admit=c.get("admit", False), char=c.get("char"), doubts=list(c.get("doubts", [])),
                     channel=c.get("channel"), provenance=c.get("provenance", ""),
                     evidence={"group": {"id": c.get("gid", "ry")}, **c.get("ev", {})}) for s, c in cells.items()]
    p = SeedAdmitParams(db_path="x", fold_groups=groups)
    n = _fold_pass(p, [ColumnAdmit(col=1, chars=recs)], {f"{B}:1:{s}": (v, None) for s, v in amap.items()})
    return n, {r.id.split(":")[-1]: r for r in recs}


def test_fold_admits_ref_in_group():
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]
    n, r = _run(("ry",), {"1": {"char": a}}, {"1": b})
    assert n == 1 and (r["1"].admit, r["1"].char, r["1"].channel) == (True, b, "fold")
    assert r["1"].evidence["fold"] == {"group": "ry", "ref": b, "via": "ref"}


def test_fold_leaves_alone():
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]
    cells = {"1": {"char": a}, "2a": {"char": a}, "3": {"char": a, "doubts": ["occluded"]},
             "4": {"char": a, "provenance": "human", "channel": "human"}, "5": {"char": a, "gid": "other"}, "6": {"char": a}}
    n, r = _run(("ry",), cells, {"1": "外", "2a": b, "3": b, "4": b, "5": b, "6": None})   # 1 整理本在组外；6 无对位
    assert n == 0
    assert _run((), {"1": {"char": a}}, {"1": b})[0] == 0
    assert "fold_groups" not in SeedAdmitParams(db_path="x").model_dump()


def test_fold_guards(tmp_path):
    from types import SimpleNamespace as NS

    from open_guji_cv.feedback.rulings import RulingStore
    from open_guji_cv.steps import seed_admit as sa
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]

    def recs():
        return [AdmitRec(id=f"{B}:1:{s}", slot=int(s), admit=s != "2", char={"1": "甲", "2": a, "3": "乙"}[s], doubts=[],
                         channel="match" if s != "2" else None, provenance="match" if s != "2" else "",
                         evidence={"group": {"id": "ry"}} if s == "2" else {}) for s in "123"]
    amap = {f"{B}:1:{s}": (c, None) for s, c in {"1": "甲", "2": b, "3": "乙"}.items()}
    mm = lambda top: {f"{B}:1:2": NS(candidates=[(top, 0.9)])}               # noqa: E731
    # 护栏二：库首位在组外 → 留审；在组内 → 放
    rr = recs(); n = sa._fold_pass(SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_lib_top_in_group=True), [ColumnAdmit(col=1, chars=rr)], amap, mm("外"))
    assert n == 0
    rr = recs(); n = sa._fold_pass(SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_lib_top_in_group=True), [ColumnAdmit(col=1, chars=rr)], amap, mm(a))
    assert n == 1 and rr[1].char == b
    # 护栏一：有本组裁定先用裁定字
    st = RulingStore(tmp_path)
    sa._L3_ONLINE.clear()
    l3 = {"ry": {"system": "s", "ver": "v1"}}
    orig = sa._l3_online
    sa._l3_online = lambda p: l3
    try:
        st.put("ry", "v1", "甲", "乙", char=a, conf="high", why="x", model="m", cell=f"{B}:1:2")
        rr = recs(); n = sa._fold_pass(SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ruling_first=True), [ColumnAdmit(col=1, chars=rr)], amap, None, store=st)
        assert n == 1 and rr[1].char == a and rr[1].evidence["fold"]["via"] == "ruling"
        rr = recs(); n = sa._fold_pass(SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ruling_first=True), [ColumnAdmit(col=1, chars=rr)], amap, None, store=RulingStore(tmp_path / "e"))
        assert n == 1 and rr[1].char == b and rr[1].evidence["fold"]["via"] == "ref"
    finally:
        sa._l3_online = orig
    assert "fold_lib_top_in_group" not in SeedAdmitParams(db_path="x", fold_groups=("ry",)).model_dump()
