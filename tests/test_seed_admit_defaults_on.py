# -*- coding: utf-8 -*-
"""2026-10-23 sheldon 定：20 册都开、没问题的放行开关一律缺省开（开关只为方便 A/B）。"""
from open_guji_cv.core.book import BookSpec
from open_guji_cv.groups.registry import FLOW_GROUPS
from open_guji_cv.steps.border_detect import BorderDetectParams
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def test_switches_default_on():
    p = SeedAdmitParams()
    assert p.context_guard_diff and p.context_guard_ref_blank and p.lane_witness3 and p.lane_coord
    assert tuple(p.group_flow) == tuple(FLOW_GROUPS)
    assert BookSpec.__dataclass_fields__["iron_gate"].default is True
    assert BorderDetectParams().pitch_rescue


def test_group_flow_can_still_be_turned_off():
    assert SeedAdmitParams(group_flow=[]).group_flow == ()
