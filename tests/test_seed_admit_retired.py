# -*- coding: utf-8 -*-
"""seed_admit 退役参数（2026-11-23 CV4 清死开关）：写缺省值的老配置照常读、照旧进指纹；写非缺省值的报错。"""
from __future__ import annotations

import pytest
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _RETIRED, _RETIRED_IN_DUMP


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
    for k in set(_RETIRED) - set(_RETIRED_IN_DUMP):
        assert k not in d


def test_codepoint_skip_follows_codepoint_lane():
    on = SeedAdmitParams(lane_coord_codepoint_variant=True).model_dump(mode="json")
    assert "lane_coord_codepoint_skip" in on
    assert "lane_coord_codepoint_skip" not in SeedAdmitParams(lane_coord_codepoint_variant=False).model_dump(mode="json")
