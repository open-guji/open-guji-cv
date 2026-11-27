"""折线落盘游程（products/kinds/cells.py，2026-11-27）：无损往返、旧的逐 x 表照读、内存里仍是逐 x 表。"""
import json

from open_guji_cv.products.kinds.cells import CellRec, PageCells, SeamCandidate, seam_runs, seam_ys


def _cell(**kw):
    return CellRec(slot=1, pos=1, y0=0.0, y1=10.0, x0=0.0, x1=5.0, kind="char", order=1, **kw)


def test_runs_roundtrip():
    ys = [5, 5, 5, 6, 8, 8, 7, 7, 7, 7]
    r = seam_runs(ys)
    assert r == {"n": 10, "runs": [[0, 5], [3, 6], [4, 8], [6, 7]]}
    assert seam_ys(r) == ys
    assert seam_runs(None) is None and seam_ys(None) is None and seam_runs([]) == []


def test_model_dumps_runs_and_loads_both():
    ys = [3] * 50 + [4, 6] + [7] * 30
    c = _cell(seam_top=ys, seam_bottom=None)
    d = c.model_dump(mode="json")
    assert d["seam_top"] == {"n": 82, "runs": [[0, 3], [50, 4], [51, 6], [52, 7]]}
    assert c.model_dump()["seam_top"] == ys              # Python 模式（不落盘）仍是逐 x 表
    assert CellRec.model_validate(d).seam_top == ys      # 新写法读回
    assert CellRec.model_validate(c.model_dump()).seam_top == ys   # 旧写法（逐 x 表）照读
    sc = SeamCandidate(kind="seam_narrow", y=ys)
    assert sc.model_dump(mode="json")["y"]["runs"][-1] == [52, 7]
    assert SeamCandidate.model_validate(json.loads(json.dumps(sc.model_dump(mode="json")))).y == ys
    assert SeamCandidate(kind="straight").model_dump(mode="json")["y"] is None


def test_page_roundtrip_equal():
    ys = list(range(10, 30)) + [30] * 40
    page = PageCells(page=1, period=100.0, ref_w=50.0, columns=[{
        "col": 1, "ok": True, "n_body_slots": 2,
        "cells": [_cell(seam_bottom=ys).model_dump(), _cell(seam_top=ys).model_dump()],
        "cut_candidates": [{"k": 1, "y": 20.0, "slot_above": 1, "slot_below": 2, "chosen": 1,
                            "candidates": [{"kind": "straight"}, {"kind": "seam_narrow", "y": ys}]}]}])
    s = json.dumps(page.model_dump(mode="json"))
    back = PageCells.model_validate(json.loads(s))
    assert back == page
    assert back.columns[0].cut_candidates[0].candidates[1].y == ys
