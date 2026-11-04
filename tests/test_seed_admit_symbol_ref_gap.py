# -*- coding: utf-8 -*-
"""symbol_ref_gap：整理本这里没字（对位无条目）也放行 ○，列内须 ≥3 个字位有对位。"""
from __future__ import annotations

from tests.test_seed_admit_symbol_ref_blank import B, NS, _run
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def _cells():
    cells = {i: {"char": "字"} for i in range(1, 5)}
    cells[9] = {"char": "○", "doubts": ["symbol"]}
    lib = {9: [("○", 0.96)]}
    return cells, lib


def test_gap_admits_when_column_aligned():
    cells, lib = _cells()
    n, r = _run(cells, lib, {1: "甲", 2: "乙", 3: "丙", 4: "丁"}, symbol_ref_gap=True, symbol_ref_gap_cov=0.95)
    assert n == 1 and r[9].admit and r[9].channel == "symbol_ref_blank"
    assert r[9].evidence["lane"]["via"] == "gap"


def test_gap_off_by_default_and_cov_floor():
    cells, lib = _cells()
    co = {1: "甲", 2: "乙", 3: "丙", 4: "丁"}
    assert _run(cells, lib, co)[0] == 0
    assert _run(cells, lib, co, symbol_ref_gap=True)[0] == 0          # cov 0.96 < 0.97


def test_gap_needs_aligned_column():
    cells, lib = _cells()
    n, _ = _run(cells, lib, {1: "甲", 2: "乙"}, symbol_ref_gap=True, symbol_ref_gap_cov=0.95)
    assert n == 0


def test_gap_params_not_in_dump_unless_on():
    assert "symbol_ref_gap" not in SeedAdmitParams(db_path="x", symbol_ref_blank="○").model_dump()
    assert "symbol_ref_gap" in SeedAdmitParams(db_path="x", symbol_ref_blank="○", symbol_ref_gap=True).model_dump()
