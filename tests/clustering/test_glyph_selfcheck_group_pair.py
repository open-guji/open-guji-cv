# -*- coding: utf-8 -*-
"""极形近字组内互撞的体检卡不出（Sheldon 2026-11-03）。"""
from open_guji_cv.clustering.glyph_selfcheck import group_pair_only


def test_group_pair_only():
    assert group_pair_only({"char": "日", "flags": ["rival"], "rival_char": "曰"})
    assert group_pair_only({"char": "己", "flags": ["rival", "rival_xbook"], "rival_char": "已", "xrival_char": "巳"})
    # 有离群旗照出
    assert not group_pair_only({"char": "日", "flags": ["rival", "outlier"], "rival_char": "曰"})
    # 对手有一个不在同组就照出
    assert not group_pair_only({"char": "日", "flags": ["rival", "rival_xbook"], "rival_char": "曰", "xrival_char": "田"})
    assert not group_pair_only({"char": "卞", "flags": ["rival"], "rival_char": "十"})
    assert not group_pair_only({"char": "日", "flags": []})
