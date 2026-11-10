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


def _grid_col():
    """满宽、上下相接的两个人工格框（0–100、100–200），每格中间一个字，邻字笔画伸进上下格。"""
    import numpy as np
    img = np.full((200, 80), 255, np.uint8)
    img[30:70, 20:60] = 0          # 格 1 的字
    img[130:170, 20:60] = 0        # 格 2 的字
    img[95:100, 30:50] = 0         # 格 2 的字头小块伸到格 1 底（框外 padding 会裹进来）
    cells = [CellRec(slot=1, pos=1, y0=0, y1=100, x0=0, x1=80, kind="char", order=0, flags=["manual"]),
             CellRec(slot=2, pos=2, y0=100, y1=200, x0=0, x1=80, kind="char", order=1, flags=["manual"])]
    cc = ColumnCells(col=3, ok=True, n_body_slots=2, cells=cells, boundaries=[],
                     flags=["roster", "manual_cells"])
    return img, cc


def test_manual_ink_fit_off_keeps_box_crop():
    from open_guji_cv.steps.cell_shrink import _roster_crops
    img, cc = _grid_col()
    (i1, _), (i2, _) = _roster_crops("b", 1, cc, img, 0.08)
    assert i2.bbox[1] < 100        # 旧行为：格 2 外扩进格 1
    assert i1.height == 100.0


def test_manual_ink_fit_shrinks_and_whitens_outside_box():
    import numpy as np
    from open_guji_cv.steps.cell_shrink import _roster_crops
    img, cc = _grid_col()
    (i1, p1), (i2, p2) = _roster_crops("b", 1, cc, img, 0.08, ink_fit=True)
    # 格 2：墨框 130–170 → 外扩 3.2 → 不越出格框上沿，裹不进格 1 的墨
    assert 100 <= i2.bbox[1] < 130 and i2.bbox[3] <= 200
    assert (i2.height, i2.width) == (40.0, 40.0)
    # 格 1：墨框含伸进来的小块（95–100），外扩到格框外的部分抹白
    x0, y0, x1, y1 = (int(v) for v in i1.bbox)
    assert y1 > 100
    assert (p1[100 - y0:, :] == 255).all()
    assert (p1 < 128).any()


def test_manual_ink_fit_switch_not_in_dump_when_off():
    from open_guji_cv.steps.cell_shrink import CellShrinkParams
    assert "manual_ink_fit" not in CellShrinkParams().model_dump(mode="json")
    assert CellShrinkParams(manual_ink_fit=True).model_dump(mode="json")["manual_ink_fit"] is True
