# -*- coding: utf-8 -*-
"""ids_plan：由成员 IDS 自动导出切分计划，应复现手写 `ids_online.SPECS` 的切向与判别位置（只用仓里的 ids_lv1 与组 override）。"""
from pathlib import Path

import pytest

from open_guji_cv.groups.ids_plan import derive_plan, diff_leaves

ROOT = Path(__file__).resolve().parents[1]


def _plan(members, gid=None):
    d = ROOT / "config" / "groups" / gid if gid else None
    return derive_plan(members, d if d and d.is_dir() else None)


def test_can_h_cut_lower_part():
    p = _plan("參㕘叅", "can")
    assert (p.mode, p.orient, p.diff, p.frame) == ("split", "h", (1,), "⿱厽{}")
    assert diff_leaves(p)[0][1] == {"參": "彡", "㕘": "小", "叅": "𠇍"}


def test_xu_v_cut_right_part():
    p = _plan("叙敘", "xu")
    assert (p.orient, p.diff) == ("v", (1,))
    assert diff_leaves(p)[0][1] == {"叙": "又", "敘": "攵"}


def test_yi_three_slots_without_hand_stops():
    p = _plan("彝彛彜彞𢑱𢑴", "yi_560")
    assert (p.mode, p.idc, p.cuts) == ("split", "⿳", 2)
    paths = [path for path, _ in diff_leaves(p)]
    assert paths == [(0,), (1, 1), (2,)]            # 上段 彑彐／中段右半 糸分／下段 廾大


def test_structure_mismatch_falls_back_to_whole():
    assert _plan("啓啟", "qik").mode == "whole"      # ⿱ 对 ⿰
    assert _plan("冊册", "ce").mode == "whole"       # ⿻ 叠合没有直线切法


def test_coarse_table_is_same_until_fine_ids_given():
    assert derive_plan("絕絶").mode == "same"        # ids_lv1 都写 ⿰糸色，分不出
    p = _plan("絕絶", "jue")                         # 组内更细的 ids 行：色 上部 刀／⺈
    assert (p.mode, p.orient) == ("split", "v")
    assert diff_leaves(p) == [((1, 0), {"絕": "刀", "絶": "⺈"})]
