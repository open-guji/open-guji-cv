"""人工指定整列格（row_segment 1.20，`lookup.resolved_manual_cells` → `_apply_manual_cells`）。"""
from types import SimpleNamespace

from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.steps.row_segment import _apply_manual_cells


def _col(n):
    return ColumnCells(col=n, ok=True, n_body_slots=3, cells=[
        CellRec(slot=1, pos=1, y0=0, y1=10, x0=0, x1=10, kind="char", order=0)])


def _env():
    gate = SimpleNamespace(period=100.0, ref_w=200.0, columns=[
        SimpleNamespace(col=n, content_x=(0.0, 100.0), border_top=0.0, border_bottom=500.0) for n in (1, 2)])
    wins = SimpleNamespace(page_size=(1000, 1000), column=lambda col: None)
    return gate, wins


def test_no_manual_is_identity():
    gate, wins = _env()
    pc = PageCells(page=5, period=100.0, ref_w=200.0, columns=[_col(1), _col(2)])
    assert _apply_manual_cells(pc, {}, gate, wins) is pc


def test_manual_replaces_only_named_column():
    gate, wins = _env()
    pc = PageCells(page=5, period=100.0, ref_w=200.0, columns=[_col(1), _col(2)])
    spec = [
        {"slot": 1, "sub": "a", "kind": "jiazhu_a", "y0": 0, "y1": 40, "x0": 60, "x1": 100},
        {"slot": 1, "sub": "b", "kind": "jiazhu_b", "y0": 10, "y1": 50, "x0": 0, "x1": 40},
        {"slot": 2, "sub": None, "kind": "char", "y0": 60, "y1": 120, "x0": 10, "x1": 90},
    ]
    out = _apply_manual_cells(pc, {2: spec}, gate, wins)
    assert out.columns[0] is pc.columns[0]
    c = out.columns[1]
    assert "roster" in c.flags and "manual_cells" in c.flags
    assert [(x.slot, x.sub) for x in c.cells] == [(1, "a"), (1, "b"), (2, None)]
    assert c.n_body_slots == 2 and c.boundaries == []
    assert c.cells[0].gap_center == 50.0 and c.cells[2].gap_center is None
