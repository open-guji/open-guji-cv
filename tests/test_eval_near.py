"""scripts/eval_near.py 的纯函数（3b 整体 benchmark，CV3，2026-11-28）。数据手造。"""
import importlib.util
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "eval_near", Path(__file__).resolve().parents[1] / "scripts" / "eval_near.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def test_isotonic_monotone_and_not_saturated():
    x = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
    y = [0, 0, 1, 0, 1, 1, 1, 1]
    kx, ky = ev.isotonic(x, y)
    assert kx == sorted(kx) and len(set(kx)) == len(kx)
    assert ky == sorted(ky)
    assert 0 < ky[0] and ky[-1] < 1                     # (正例+0.5)/(n+1)，不出 0／1
    assert float(np.interp(0.05, kx, ky)) == ky[0]      # 两端外取端点


def test_ece_perfect_and_overconfident():
    assert ev.ece([0.9] * 10, [True] * 9 + [False]) == 0.0
    assert ev.ece([0.99] * 4, [True, True, False, False]) == 0.49
    assert ev.ece([], []) is None


def test_truth_gold_first_and_circular_channel_dropped():
    circ = {"rr_shape"}
    assert ev.truth({"label": {"char": "入", "channel": "human", "gold_char": "人"}}, circ) == "人"
    assert ev.truth({"label": {"char": "入", "channel": "rr_shape"}}, circ) is None
    assert ev.truth({"label": {"char": "入", "channel": "text"}}, circ) == "入"
    assert ev.truth({"label": {"char": "入", "channel": "text"}}, circ, gold_only=True) is None
    assert ev.truth({"label": None}, circ) is None


def test_mfold_only_method_merge_not_group_fold():
    class Hou:                                           # 没有 merge：严格比
        chars = ["候", "𠋫"]

    class Cnn:
        merge = {"宮": "宫"}
        classes = ["官", "宫"]

    assert ev.mfold(Hou()) == {}
    assert ev.canon("𠋫", ev.mfold(Hou())) != ev.canon("候", ev.mfold(Hou()))
    assert ev.canon("宮", ev.mfold(Cnn())) == "宫"


def test_pick_of_abstain_and_stroke_veto():
    assert ev.pick_of({"evidence": {"method": "rr_shape", "char": "入"}}) == ("入", False)
    assert ev.pick_of({"evidence": {"method": "pair_shape", "char": None, "why": "abstain:gap"}}) == (None, True)
    assert ev.pick_of({"evidence": {"method": "stroke_veto", "cls": "千"}}) == ("千", False)
    assert ev.pick_of({"evidence": {}, "sims": {"甲": 0.2, "乙": 0.7}}) == ("乙", False)
    assert ev.pick_of({"evidence": {"error": "x"}}) == (None, True)


def test_calib_path_file_and_dir(tmp_path):
    assert ev.calib_path("config/groups/rr_shape.json", tmp_path).name == "rr_shape.calib.json"
    assert ev.calib_path("models/glyph_near_gong", tmp_path) == tmp_path / "models/glyph_near_gong/calib.json"
