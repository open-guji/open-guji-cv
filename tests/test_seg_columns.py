# -*- coding: utf-8 -*-
"""`seg/columns`：列宽均匀约束原语（自造数据）。"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.seg.columns import (Cand, ColumnSpec, blank_mids, check_columns, fit_columns, flank_ink,
                                      thin_peaks)


def test_spec_from_dict_and_validation():
    s = ColumnSpec.from_dict({"uniform": "loose", "inner_band": [0.8, 1.2], "pitch": 120})
    assert s.uniform == "loose" and s.inner_band == (0.8, 1.2) and s.pitch == 120.0
    assert ColumnSpec.from_dict(None) == ColumnSpec()
    with pytest.raises(ValueError):
        ColumnSpec.from_dict({"uniform": "maybe"})
    with pytest.raises(ValueError):
        ColumnSpec.from_dict({"band": [1, 2]})


def test_check_columns_inner_outer_and_skip():
    xs = [0, 100, 200, 300, 400, 500, 600, 700, 800, 925]        # 末列 1.25：外列带内
    assert check_columns(xs, ColumnSpec()).ok
    xs2 = [0, 100, 200, 250, 400, 500, 600, 700, 800, 900]       # c3 0.5、c4 1.5
    assert check_columns(xs2, ColumnSpec()).bad == [3, 4]
    assert check_columns(xs2, ColumnSpec(), skip={3, 4}).ok
    assert not check_columns([0, 100, 300], ColumnSpec()).judged     # 列太少不判
    assert check_columns(xs, ColumnSpec(pitch=80)).bad               # 先验列距 80：全偏宽


def test_fit_picks_even_chain_and_prefers_evidence():
    # 真网 0..900 步 100；50 处一条高分假线；300 处缺线，只有低分空白中点
    cands = [Cand(x, 2.0) for x in (0, 100, 200, 400, 500, 600, 700, 800, 900)] + [Cand(50, 2.0), Cand(300, 0.5)]
    chain = fit_columns(cands, 10, 100.0, ColumnSpec())
    assert [c.x for c in chain] == [0, 100, 200, 300, 400, 500, 600, 700, 800, 900]
    assert fit_columns(cands[:9], 10, 100.0, ColumnSpec()) is None          # 凑不够线


def test_fit_first_max_last_min():
    cands = [Cand(x, 1.0) for x in range(0, 1100, 100)]                    # 11 条，挑 10 条：两种平移
    assert [c.x for c in fit_columns(cands, 10, 100.0, ColumnSpec(), first_max=50)][0] == 0
    assert [c.x for c in fit_columns(cands, 10, 100.0, ColumnSpec(), last_min=1000)][-1] == 1000


def test_profile_helpers():
    xs = np.arange(0, 100)
    prof = np.zeros(100)
    prof[20:40] = 0.3            # 一列字
    prof[60] = 0.2               # 淡界行细峰
    prof[80:95] = 0.3
    assert blank_mids(xs, prof) == [49.5, 70.0]          # 40–59、61–79 两段
    assert thin_peaks(xs, prof) == [60.0]
    assert flank_ink(xs, prof, 30) > 0.1 and flank_ink(xs, prof, 60) == 0.0
