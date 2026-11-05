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


def test_fold_coord_ref():
    from types import SimpleNamespace as NS

    from open_guji_cv.steps import seed_admit as sa
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]
    rid = f"{B}:1:1"

    def rec(group=True):
        return AdmitRec(id=rid, slot=1, admit=False, char=a, doubts=[], channel=None, provenance="",
                        evidence={"group": {"id": "ry"}} if group else {})
    on = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_coord_ref=True, fold_lib_top_in_group=True)
    mm = lambda top: {rid: NS(candidates=[(top, 0.9)])}                      # noqa: E731
    # ① 现役对位缺 → 用坐标对位
    r = rec(); assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], {}, mm(a), coord={rid: b}) == 1
    assert r.char == b and r.evidence["fold"] == {"group": "ry", "ref": b, "via": "ref", "coord": True}
    r = rec(); assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], {}, mm(a), coord={rid: "〓"}) == 0
    # 关时不用坐标对位
    off = SeedAdmitParams(db_path="x", fold_groups=("ry",))
    r = rec(); assert sa._fold_pass(off, [ColumnAdmit(col=1, chars=[r])], {}, mm(a), coord={rid: b}) == 0
    # ② 未入组格：库首位与整理本同组 → 折；库首位在组外 → 不折
    r = rec(False); assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], {}, mm(a), coord={rid: b}) == 1
    assert r.evidence["fold"]["group"] == "ry"
    r = rec(False); assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], {}, mm("外"), coord={rid: b}) == 0
    r = rec(False); assert sa._fold_pass(off, [ColumnAdmit(col=1, chars=[r])], {rid: (b, None)}, mm(a)) == 0
    assert "fold_coord_ref" not in SeedAdmitParams(db_path="x", fold_groups=("ry",)).model_dump()
    assert "fold_coord_ref" not in SeedAdmitParams(db_path="x", fold_coord_ref=True).model_dump()
    assert on.model_dump()["fold_coord_ref"] is True


def test_fold_by_meaning(tmp_path, monkeypatch):
    """新语义（sheldon 11-05）：归组后按文意定字，不看整理本；没有裁定就留审；jys 从 abstain_ref_ok 里去掉。"""
    from types import SimpleNamespace as NS

    import numpy as np

    from open_guji_cv.feedback.rulings import RulingStore
    from open_guji_cv.steps import seed_admit as sa
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]
    rid = f"{B}:1:1"
    rec = lambda: AdmitRec(id=rid, slot=1, admit=False, char=a, doubts=[], channel=None, provenance="",  # noqa: E731
                           evidence={"group": {"id": "ry"}})
    on = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_by_meaning=True)
    amap = {rid: (b, None)}                                          # 整理本字 b：新语义下不得被取用
    # 没有裁定、没开字形 → 留审，记归组
    r = rec(); assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], amap, None, store=RulingStore(tmp_path / "e")) == 0
    assert not r.admit and r.evidence["fold_pending"]["group"] == "ry"
    # 有文意裁定 → 放裁定字（可以与整理本不同）
    st = RulingStore(tmp_path)
    sa._L3_ONLINE.clear()
    monkeypatch.setattr(sa, "_l3_online", lambda p: {"ry": {"system": "s", "ver": "v1"}})
    monkeypatch.setattr(sa, "_clf_ctx", lambda *a_, **k: "w")
    st.put("ry", "v1", "w", "w", char=a, conf="high", why="x", model="m", cell=rid)
    r = rec(); assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], amap, None, store=st) == 1
    assert r.char == a and r.channel == "fold" and r.evidence["fold"]["via"] == "ruling" and r.evidence["fold"]["ref"] is None
    # 字形一路：宽高比 ≤0.85 日、≥1.0 曰、中间留审
    import open_guji_cv.groups.aspect as asp
    asp_on = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_by_meaning=True, fold_aspect=(0.85, 1.0))
    monkeypatch.setattr(sa, "_page_patch", lambda *a_, **k: np.zeros((4, 4), np.uint8))
    for ratio, want in ((0.7, "日"), (1.1, "曰"), (0.9, None)):
        monkeypatch.setattr(asp, "aspect", lambda g, ratio=ratio: ratio)
        r = rec(); n = sa._fold_pass(asp_on, [ColumnAdmit(col=1, chars=[r])], amap, None, store=RulingStore(tmp_path / "e2"),
                                     ctx=NS(), page=1)
        assert (n == 1) == (want is not None) and (want is None or (r.char == want and r.evidence["fold"]["via"] == "aspect"))
    # 库首位在组内但字组流程没入组的格也归组
    r = AdmitRec(id=rid, slot=1, admit=False, char="外", doubts=[], channel=None, provenance="", evidence={})
    assert sa._fold_pass(on, [ColumnAdmit(col=1, chars=[r])], amap, {rid: NS(candidates=[(a, 0.9)])}, store=st) == 1
    # jys 从 abstain_ref_ok 里去掉；默认不进 dump
    q = SeedAdmitParams(db_path="x", group_flow_abstain_ref_ok=["jys", "xx"], fold_groups=("jys",), fold_by_meaning=True)
    assert q._rt_abstain_ref_ok() == frozenset({"xx"})
    assert SeedAdmitParams(db_path="x", group_flow_abstain_ref_ok=["jys"], fold_groups=("jys",))._rt_abstain_ref_ok() == frozenset({"jys"})
    d = SeedAdmitParams(db_path="x", fold_groups=("ry",)).model_dump()
    assert "fold_by_meaning" not in d and "fold_aspect" not in d
    assert on.model_dump()["fold_by_meaning"] is True and "fold_aspect" not in on.model_dump()
