# -*- coding: utf-8 -*-
"""切线金标的页面坐标（eval/colgeom.py）：换了列窗几何也能换算到当前列图。"""
from __future__ import annotations

import pytest

from open_guji_cv.eval.colgeom import ColumnGeom, gold_rows_now, stamp
from open_guji_cv.gold.atomic import CUTLINE_KEYS, merge_expected


def _rec(x_left=1200.0, x_right=1020.0, slope=0.01, top=330.0, bottom=2750.0, segments=1):
    line = lambda x: {"x_at_top": x, "slope": slope, "segments": segments,
                      "k2": None, "k3": None, "y1": None, "y2": None}
    return {"left_line": line(x_left), "right_line": line(x_right), "top_y": top, "bottom_y": bottom}


def test_row_page_round_trip():
    g = ColumnGeom(_rec(), 3000)
    for r in (0.0, 512.3, 1777.7, g.height - 1):
        x, y = g.row_to_page(r)
        assert g.page_to_row(x, y)[0] == pytest.approx(r, abs=1e-3)


def test_page_coordinates_survive_a_geometry_change():
    """同一处页面位置，边线挪了以后行号变了——按页面坐标换算能跟上，原坐标会漂。"""
    old, new = ColumnGeom(_rec(), 3000), ColumnGeom(_rec(slope=0.03, top=300.0), 3000)
    assert old.sig != new.sig
    ex = {"y": 1200.0, "polyline": [[0, 1195], [170, 1205]]}
    ex.update(stamp(ex, old))
    mode, y_now, pl_now = gold_rows_now(ex, new)
    x, y = old.row_to_page(1200.0)
    assert mode == "page" and y_now == pytest.approx(new.page_to_row(x, y)[0], abs=1e-6)
    assert abs(y_now - 1200.0) > 20                      # 真的漂了：原坐标不能直接用
    assert len(pl_now) == 2


def test_signature_only_and_legacy_modes():
    g, g2 = ColumnGeom(_rec(), 3000), ColumnGeom(_rec(top=310.0), 3000)
    assert gold_rows_now({"y": 5.0, "geom_sig": g.sig}, g) == ("sig_ok", 5.0, None)
    assert gold_rows_now({"y": 5.0, "geom_sig": g.sig}, g2)[0] == "drift"
    assert gold_rows_now({"y": 5.0}, g2) == ("legacy", 5.0, None)
    assert stamp({"y": 5.0}, None) == {}


def test_stamp_keys_are_replaced_as_one_group():
    """新裁决没带页面坐标（取不到几何）时，旧的 page_y 不能残留下来配新的 y。"""
    for k in ("geom_sig", "page_x", "page_y", "page_polyline"):
        assert k in CUTLINE_KEYS
    old = {"y": 100.0, "page_y": 999.0, "page_x": 1.0, "geom_sig": "abc"}
    merged = merge_expected("char-segmentation/touching-cuts", old, {"y": 120.0, "verdict": "moved"})
    assert "page_y" not in merged and merged["y"] == 120.0
