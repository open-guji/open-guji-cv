# -*- coding: utf-8 -*-
"""2026-10-23 sheldon 定：20 册都开、没问题的放行开关一律缺省开（开关只为方便 A/B）。"""
from open_guji_cv.core.book import BookSpec
from open_guji_cv.groups.registry import FLOW_GROUPS, generic_flow_names
from open_guji_cv.steps.border_detect import BorderDetectParams
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def test_switches_default_on():
    p = SeedAdmitParams()
    assert p.context_guard_diff and p.context_guard_ref_blank and p.lane_witness3 and p.lane_coord
    assert tuple(p.group_flow) == generic_flow_names()
    assert BookSpec.__dataclass_fields__["iron_gate"].default is True
    assert BorderDetectParams().pitch_rescue


def test_group_flow_can_still_be_turned_off():
    assert SeedAdmitParams(group_flow=[]).group_flow == ()


def test_default_group_flow_has_no_codepoint_groups():
    """多书设计 A3（sheldon 11-04）：缺省只跑通用字组，不含殿本的码位组 cp_*；要用显式写进 group_flow。"""
    d = tuple(SeedAdmitParams().group_flow)
    assert d and not any(g.startswith("cp_") for g in d)
    assert set(d) == {g for g in FLOW_GROUPS if not g.startswith("cp_")}
    assert any(g.startswith("cp_") for g in FLOW_GROUPS)            # 注册表里的码位组还在


def test_explicit_full_group_flow_is_old_default():
    """没写 group_flow 的老书（史記、全唐文）把「全集」显式写进基础配置，参数 dump 与旧缺省逐字相同，指纹不变。"""
    full = SeedAdmitParams(group_flow=tuple(FLOW_GROUPS))
    assert tuple(full.group_flow) == tuple(FLOW_GROUPS) and len(full.group_flow) > len(SeedAdmitParams().group_flow)
