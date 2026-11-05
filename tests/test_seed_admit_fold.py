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
    assert r["1"].evidence["fold"] == {"group": "ry", "ref": b}


def test_fold_leaves_alone():
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]
    cells = {"1": {"char": a}, "2a": {"char": a}, "3": {"char": a, "doubts": ["occluded"]},
             "4": {"char": a, "provenance": "human", "channel": "human"}, "5": {"char": a, "gid": "other"}, "6": {"char": a}}
    n, r = _run(("ry",), cells, {"1": "外", "2a": b, "3": b, "4": b, "5": b, "6": None})   # 1 整理本在组外；6 无对位
    assert n == 0
    assert _run((), {"1": {"char": a}}, {"1": b})[0] == 0
    assert "fold_groups" not in SeedAdmitParams(db_path="x").model_dump()
