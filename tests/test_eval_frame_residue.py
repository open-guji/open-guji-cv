# -*- coding: utf-8 -*-
"""eval_frame_residue._base_case：剥 trim.case 后缀要按「先 i 后数字」的顺序，
反了会把 a3i 这类两个后缀都有的剥不干净（2026-09-27 全书扫描实测踩过：a3i 剥成
了 a3、没能并进 a）。"""
import importlib.util
import sys
from pathlib import Path

import cv2  # noqa: F401  确保引擎依赖已装，脚本内部 import 链要用

_SPEC = importlib.util.spec_from_file_location(
    "eval_frame_residue", Path(__file__).resolve().parent.parent / "scripts" / "eval_frame_residue.py")
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_frame_residue"] = _MOD
_SPEC.loader.exec_module(_MOD)


def test_base_case_strips_digit_and_i_in_either_order():
    cases = {
        "a": "a", "a2": "a", "a3": "a", "ai": "a", "a3i": "a",
        "b": "b", "bi": "b",
        "c": "c", "ci": "c",
        "d": "d", "d2": "d", "d3": "d", "di": "d", "d2i": "d",
        "e": "e", "e2": "e", "ei": "e",
    }
    for raw, expected in cases.items():
        assert _MOD._base_case(raw) == expected, raw
