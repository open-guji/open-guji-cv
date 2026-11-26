"""整列钉子按写入时的列图几何底换算到现行列图（CV0 11-26 批的钉子护栏）。"""
from types import SimpleNamespace as NS

from open_guji_cv.products.kinds.borders import VLineRec
from open_guji_cv.steps import row_segment as rs
from open_guji_cv.steps._warpmap import ColumnMapper

PW = 2000


def _wrec(left, right, top=100.0, bottom=1900.0):
    return NS(left_line=VLineRec(**left), right_line=VLineRec(**right), top_y=top, bottom_y=bottom, ruled=False)


def _wins(wrec):
    return NS(page_size=(PW, 2400), column=lambda c: wrec if c == 3 else None)


STRAIGHT = ({"x_at_top": 900.0, "slope": 0.002}, {"x_at_top": 1100.0, "slope": 0.002})
#: 同斜率三段（outer_bar 让整页成三段时内侧列的样子）：几何上同一条线，列图按三带矫正
BENT = ({"x_at_top": 900.0, "slope": 0.002, "k2": 0.002, "k3": 0.002, "y1": 500.0, "y2": 1500.0},
        {"x_at_top": 1100.0, "slope": 0.002, "k2": 0.002, "k3": 0.002, "y1": 500.0, "y2": 1500.0})
SPEC = [{"slot": 1, "kind": "char", "x0": 20.0, "x1": 180.0, "y0": 300.0, "y1": 460.0},
        {"slot": 2, "kind": "char", "x0": 20.0, "x1": 180.0, "y0": 1300.0, "y1": 1460.0}]


def _geom(wrec):
    return {"v": 1, **rs._geom_of(wrec, PW)}


def test_same_geom_untouched():
    w = _wrec(*STRAIGHT)
    out, flagged = rs._remap_manual({3: SPEC}, {3: _geom(w)}, _wins(w), 7)
    assert out[3] is SPEC and not flagged


def test_no_geom_untouched(capsys):
    w = _wrec(*BENT)
    out, flagged = rs._remap_manual({3: SPEC}, {}, _wins(w), 7)
    assert out[3] is SPEC and not flagged
    assert "没记列图几何底" in capsys.readouterr().err


def test_remap_lands_on_same_page_pixels():
    old_w, new_w = _wrec(*STRAIGHT, top=60.0), _wrec(*BENT)
    out, flagged = rs._remap_manual({3: SPEC}, {3: _geom(old_w)}, _wins(new_w), 7)
    assert flagged == {3}                                   # 上界挪了 40px，送人核
    old_m, new_m = ColumnMapper.of(PW, old_w), ColumnMapper.of(PW, new_w)
    for a, b in zip(SPEC, out[3]):
        for (x, y), (nx, ny) in (((a["x0"], a["y0"]), (b["x0"], b["y0"])), ((a["x1"], a["y1"]), (b["x1"], b["y1"]))):
            px, py = old_m.to_page_tl(x, y)
            qx, qy = new_m.to_page_tl(nx, ny)
            assert abs(px - qx) < 1.5 and abs(py - qy) < 1.5


def test_small_shift_not_flagged():
    old_w = _wrec(*STRAIGHT, top=101.0)
    out, flagged = rs._remap_manual({3: SPEC}, {3: _geom(old_w)}, _wins(_wrec(*STRAIGHT)), 7)
    assert not flagged and abs(out[3][0]["y0"] - (SPEC[0]["y0"] + 1.0)) < 0.2


def test_page_manual_geom_reads_basis(tmp_path, monkeypatch):
    import json
    from open_guji_cv.gold import store as gs
    d = tmp_path / "char-segmentation" / "manual-cells"
    d.mkdir(parents=True)
    g = {"v": 1, "page_w": PW, "left": [1, 0, None, None, None, None]}
    rows = [{"id": "b1:7:3", "anchor": {"book": "b1", "page": 7, "col": 3}, "status": "active", "label_origin": "human",
             "expected": {"cells": SPEC}, "input": {"column_basis": {"col_sha": "x", "geom": g}},
             "history": [{"ts": "2026-11-26T00:00:00Z", "change": "created", "why": "t"}]},
            {"id": "b1:7:4", "anchor": {"book": "b1", "page": 7, "col": 4}, "status": "active", "label_origin": "human",
             "expected": {"cells": SPEC}, "input": {},
             "history": [{"ts": "2026-11-26T00:00:00Z", "change": "created", "why": "t"}]}]
    (d / "items.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(gs, "verdict_store", lambda: gs.GoldStore(tmp_path))
    assert rs._page_manual_geom("b1", 7) == {3: g}
    assert rs._page_manual_geom("b1", 8) == {}
