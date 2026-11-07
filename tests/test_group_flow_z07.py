# -*- coding: utf-8 -*-
"""Z07 差一路确认（A24 2026-11-07）：`flow._ref_pair_coord_pick`。

联合判卡在「共字组搭档没表态」、现役对位缺这一格时，坐标对位字＝本组给的字、没有任何解法给别字 → 取它。
trail 是殿本 ★main 包里真实格的解法留痕（精简），看图定的真字写在注释里。"""
from __future__ import annotations

from types import SimpleNamespace

from open_guji_cv.groups.flow import FlowConfig, _ref_pair_coord_pick


def canon(c):
    return c


def T(solver, char, why="agree"):
    return {"solver": solver, "char": char, "why": why}


def R(i="vol20:241:4:9"):
    return SimpleNamespace(id=i)


def test_default_off():
    assert FlowConfig(groups=()).ref_pair_coord is False


def test_coord_image_solver_partner_silent():
    # vol20:241:4:9「皆爲[未]密」放行字 末，坐标对位 未；bars 判未，文意待裁，搭档 sz 没表态（看图：未）
    trail = [T("ctx", None, "abstain:llm_pending"), T("bars", "未"), T("sz:ids", None, "abstain:low_margin")]
    assert _ref_pair_coord_pick("wm", R(), trail, "未", canon) == "未"


def test_coord_prefers_ctx_char():
    # vol68:64:9:13「字白[閩]淸人」文意判閩、搭档 wj 弃权（看图：閩）
    trail = [T("ids", None, "abstain:low_margin"), T("ctx", "閩"), T("wj:ctx", None, "abstain:other"), T("vis", None, "abstain:llm_pending")]
    assert _ref_pair_coord_pick("men", R("vol68:64:9:13"), trail, "閩", canon) == "閩"


def test_blocked_when_any_solver_dissents():
    # 图像路给了别字也不取（比 ref_pair 严）
    trail = [T("ctx", "未"), T("bars", "末")]
    assert _ref_pair_coord_pick("wm", R(), trail, "未", canon) is None
    # 搭档给了别字不取
    trail = [T("ctx", "于"), T("yz:ctx", "子")]
    assert _ref_pair_coord_pick("zy", R(), trail, "于", canon) is None


def test_blocked_gap_halfcell_nonmember_or_partner_only():
    trail = [T("ctx", "未")]
    assert _ref_pair_coord_pick("wm", R(), trail, "〓", canon) is None
    assert _ref_pair_coord_pick("wm", R("vol20:241:4:9a"), trail, "未", canon) is None
    assert _ref_pair_coord_pick("wm", R(), trail, "宋", canon) is None
    assert _ref_pair_coord_pick("wm", R(), trail, None, canon) is None
    # 只有搭档给了（本组没一路给）不取
    assert _ref_pair_coord_pick("zy", R(), [T("ctx", None, "abstain"), T("yz:ctx", "于")], "于", canon) is None


def test_seed_admit_param_off_not_dumped():
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    assert "group_flow_ref_pair_coord" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(group_flow_ref_pair_coord=True).model_dump()["group_flow_ref_pair_coord"] is True
