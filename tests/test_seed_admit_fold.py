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


def test_fold_no_ref_char_aspect_and_pending(tmp_path):
    """fold_ref_char=False：不取整理本字；日曰按宽高比（≥1.0 曰、≤0.85 日），居中留审并记 fold_pending；有裁定用裁定。"""
    from types import SimpleNamespace as NS

    from open_guji_cv.feedback.rulings import RulingStore
    from open_guji_cv.steps import seed_admit as sa
    p = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ref_char=False, fold_aspect=(0.85, 1.0))
    d = p.model_dump()
    assert d["fold_ref_char"] is False and d["fold_aspect"] == (0.85, 1.0)
    d0 = SeedAdmitParams(db_path="x", fold_groups=("ry",)).model_dump()
    assert "fold_ref_char" not in d0 and "fold_aspect" not in d0

    WH = {}

    def rec(s, wh):
        r = AdmitRec(id=f"{B}:1:{s}", slot=int(s), admit=False, char="乙", doubts=[], channel=None, provenance="",
                     evidence={"group": {"id": "ry"}})
        WH[r.id] = (wh * 100, 100)
        return r
    amap = lambda rs: {r.id: ("日", None) for r in rs}   # noqa: E731  整理本一律给「日」：不许被取
    rs = [rec("1", 1.1), rec("2", 0.7), rec("3", 0.92)]
    n = sa._fold_pass(p, [ColumnAdmit(col=1, chars=rs)], amap(rs), None, store=RulingStore(tmp_path / "e"), wh=WH)
    assert n == 2 and (rs[0].char, rs[0].evidence["fold"]["via"]) == ("曰", "aspect")
    assert rs[1].char == "日" and rs[1].evidence["fold"]["aspect"] == 0.7
    assert not rs[2].admit and rs[2].evidence["fold_pending"] == {"group": "ry"} and rs[2].char == "乙"
    # 居中格有本组裁定：放裁定字（不是整理本字）
    st = RulingStore(tmp_path / "s")
    orig, sa._l3_online = sa._l3_online, (lambda p_: {"ry": {"system": "s", "ver": "v1"}})
    try:
        st.put("ry", "v1", "", "", char="曰", conf="high", why="x", model="m", cell=f"{B}:1:3")
        rs = [rec("3", 0.92)]
        rs[0].slot = 1
        seq_amap = {rs[0].id: ("日", None)}
        n = sa._fold_pass(p, [ColumnAdmit(col=1, chars=rs)], seq_amap, None, store=st, wh=WH)
        assert n == 1 and rs[0].char == "曰" and rs[0].evidence["fold"]["via"] == "ruling"   # 无邻格，窗口键为空串
    finally:
        sa._l3_online = orig


def test_fold_occluded_needs_switch_and_ref_lib_both_in_group(tmp_path):
    """fold_occluded：遮挡格默认不碰；开了之后整理本字与库首位同在折叠组才归组，不取整理本字（fold_ref_char=false 时只放文意裁定／宽高判据）。"""
    from types import SimpleNamespace as NS

    from open_guji_cv.steps import seed_admit as sa
    m = sorted(FLOW_GROUPS["ry"].members)
    a, b = m[0], m[1]

    def rec():
        return [AdmitRec(id=f"{B}:1:1", slot=1, admit=False, char="乙", doubts=["occluded"], channel=None, provenance="",
                         evidence={"occluded": True})]
    amap = {f"{B}:1:1": (b, None)}
    mm = lambda top: {f"{B}:1:1": NS(candidates=[(top, 0.9)])}                  # noqa: E731
    p0 = SeedAdmitParams(db_path="x", fold_groups=("ry",))                      # 旧口径：放整理本字
    rr = rec(); assert sa._fold_pass(p0, [ColumnAdmit(col=1, chars=rr)], amap, mm(a)) == 0      # 默认不碰遮挡格
    p1 = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_occluded=True)
    rr = rec(); assert sa._fold_pass(p1, [ColumnAdmit(col=1, chars=rr)], amap, mm("外")) == 0   # 库首位在组外
    rr = rec(); assert sa._fold_pass(p1, [ColumnAdmit(col=1, chars=rr)], {f"{B}:1:1": ("外", None)}, mm(a)) == 0   # 整理本字在组外
    rr = rec(); assert sa._fold_pass(p1, [ColumnAdmit(col=1, chars=rr)], amap, mm(a)) == 1 and rr[0].char == b   # 旧口径才放整理本字
    p2 = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_occluded=True, fold_ref_char=False)
    rr = rec()
    assert sa._fold_pass(p2, [ColumnAdmit(col=1, chars=rr)], amap, mm(a), store=__import__("open_guji_cv.feedback.rulings", fromlist=["RulingStore"]).RulingStore(tmp_path)) == 0
    assert not rr[0].admit and rr[0].evidence["fold_pending"] == {"group": "ry"}                # 不取整理本字，留审
    assert "fold_occluded" not in SeedAdmitParams(db_path="x", fold_groups=("ry",)).model_dump()
    assert SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_occluded=True).model_dump()["fold_occluded"] is True
