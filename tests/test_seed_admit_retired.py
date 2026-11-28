# -*- coding: utf-8 -*-
"""seed_admit 退役参数（2026-11-23 CV4 清死开关）：写缺省值的老配置照常读、照旧进指纹；写非缺省值的报错。"""
from __future__ import annotations

import pytest
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _ALWAYS_ON, _ALWAYS_ON_IN_DUMP, _RETIRED, _RETIRED_IN_DUMP
from open_guji_cv.steps.seed_admit_params import _CONSTANTS


def test_retired_default_values_ignored():
    p = SeedAdmitParams(**_RETIRED)
    assert p.model_dump() == SeedAdmitParams().model_dump()


def test_retired_non_default_raises():
    with pytest.raises(ValueError, match="退役"):
        SeedAdmitParams(witness3_no_diff=True)
    with pytest.raises(ValueError, match="退役"):
        SeedAdmitParams(off_channels=["context"])


def test_dump_keeps_retired_fixed_values():
    d = SeedAdmitParams().model_dump(mode="json")
    for k, v in _RETIRED_IN_DUMP.items():
        if k == "lane_coord_codepoint_skip":          # 只在码位异体 lane 开着时进 dump（与退役前同）
            continue
        assert k in d and d[k] == (list(v) if isinstance(v, tuple) else v)
    for k in set(_RETIRED) - set(_RETIRED_IN_DUMP) - set(_ALWAYS_ON) - set(_CONSTANTS):
        assert k not in d


def test_codepoint_skip_follows_codepoint_lane():
    on = SeedAdmitParams(lane_coord_codepoint_variant=True).model_dump(mode="json")
    assert "lane_coord_codepoint_skip" in on
    assert "lane_coord_codepoint_skip" not in SeedAdmitParams(lane_coord_codepoint_variant=False).model_dump(mode="json")


def test_always_on_keys():
    """恒开的护栏（2026-11-23 PR2）：写 true 照读、写 false 报错；不进 dump 的照旧不进。"""
    assert SeedAdmitParams(**{k: True for k in _ALWAYS_ON}).model_dump() == SeedAdmitParams().model_dump()
    with pytest.raises(ValueError, match="退役"):
        SeedAdmitParams(edge_pair=False)
    d = SeedAdmitParams(rare_ref=True, lane_seal=True).model_dump(mode="json")
    assert all(k not in d for k in set(_ALWAYS_ON) - set(_ALWAYS_ON_IN_DUMP))
    assert d["rare_ref_coord"] is True and d["iron_ref_guard"] is True


def test_constants_are_read_only_attrs_and_keep_dump():
    """收成常量的门槛（2026-11-24 PR4）：不再是字段，`p.<名>` 照读常量；写原值照读、写别的值报错；dump 照旧带上（按原条件去键）。"""
    p = SeedAdmitParams()
    for k, v in _CONSTANTS.items():
        assert k not in SeedAdmitParams.model_fields
        assert getattr(p, k) == v
    assert SeedAdmitParams(solo_cov=0.99).model_dump() == p.model_dump()
    with pytest.raises(ValueError, match="退役"):
        SeedAdmitParams(solo_cov=0.98)
    d = p.model_dump(mode="json")
    assert d["solo_cov"] == 0.99 and d["context_margin"] == 0.7
    assert "p_ref_min_cov" not in d                          # 原先缺省不进 dump 的，照旧不进
