"""2d′ `free_to_cells`：自由版式 free_cells／free_columns → 标准 cells／column_windows／column_image（默认链第二期）。

合成页同 `test_free_layout`（上下两块各 10 列；每列大字、双行小注、大字）。"""

from __future__ import annotations

import copy

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册 Step
from open_guji_cv.core.anchor import bbox_tr_to_tl
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.core.spec import column_key
from open_guji_cv.impl.free.free_map import warp_points
from open_guji_cv.impl.free.free_rectify import warp_maps
from open_guji_cv.products.kinds.borders import VLineRec
from open_guji_cv.products.kinds.columns import ColumnWindowRec
from open_guji_cv.steps._warpmap import ColumnMapper, FreeColumnMapper
from tests.helpers import make_book, make_ctx, run_steps
from tests.test_free_layout import synth_free_page

STEPS = ["block_detect", "column_trace", "cell_cut", "free_to_cells"]


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    img, expect = synth_free_page()
    ctx = make_ctx(tmp_path_factory.mktemp("f2c"), make_book("tfree", layout="free"), raw={1: img})
    out = run_steps(ctx, 1, STEPS + ["cell_shrink"])
    return ctx, out, expect


def test_free_layout_runs_skeleton_tail():
    steps = load_pipeline("guji_default", layout="free").steps
    assert steps[steps.index("cell_cut") + 1] == "free_to_cells"
    assert steps[steps.index("free_to_cells") + 1] == "cell_shrink"
    assert steps[-1] == "char_decide"
    assert "free_to_cells" not in load_pipeline("guji_default", layout="grid").steps


def test_slots_and_note_pairs(ran):
    _, out, expect = ran
    ok = 0
    for cc, (n_big, n_note) in zip(out["cells"].columns, expect):
        pos_kinds: dict[int, set] = {}
        for c in cc.cells:
            pos_kinds.setdefault(c.pos, set()).add(c.kind)
        pairs = sum(1 for v in pos_kinds.values() if v == {"jiazhu_a", "jiazhu_b"})
        bigs = sum(1 for v in pos_kinds.values() if v == {"char"})
        ok += cc.n_body_slots == n_big + n_note and pairs == n_note and bigs == n_big
        assert len(cc.boundaries) == cc.n_body_slots + 1
        assert cc.boundaries == sorted(cc.boundaries)
    assert ok >= 18, f"逐列全对 {ok}/20"


def test_reading_order_and_cell_count(ran):
    _, out, _ = ran
    free = out["free_cells"].cells
    assert sum(len(cc.cells) for cc in out["cells"].columns) == len(free)
    for cc in out["cells"].columns:
        mine = sorted((c for c in free if c.col == cc.col), key=lambda c: c.order)
        assert sorted(c.order for c in cc.cells) == [c.order - 1 for c in mine]
        a = [c.order for c in cc.cells if c.sub == "a"]
        b = [c.order for c in cc.cells if c.sub == "b"]
        if a and b:
            assert max(a) < min(b)          # 小注右行先读完


def test_quad_page_back_on_free_box(ran):
    _, out, _ = ran
    W = out["free_cells"].width
    by = {(c.col, c.order - 1): c for c in out["free_cells"].cells}
    for cc in out["cells"].columns:
        for c in cc.cells:
            x0, y0, x1, y1 = bbox_tr_to_tl(by[(cc.col, c.order)].box, W)
            q = np.asarray(c.quad_page)
            qx = W - 1 - q[:, 0]
            assert abs(qx.min() - x0) <= 1.5 and abs(qx.max() - (x1 + 1)) <= 1.5
            assert abs(q[:, 1].min() - y0) <= 1.5 and abs(q[:, 1].max() - (y1 + 1)) <= 1.5


def test_column_image_ink(ran):
    ctx, out, _ = ran
    for cc in out["cells"].columns[:5]:
        img = ctx.image("column_image", column_key(1, cc.col))
        assert img.shape == (int(out["column_windows"].column(cc.col).warped_size[1]),
                             int(out["column_windows"].column(cc.col).warped_size[0]))
        for c in cc.cells:
            patch = img[int(c.y0):int(c.y1), int(c.x0):int(c.x1)]
            assert (patch < 100).mean() > 0.05


def test_render_matches_cache(ran):
    ctx, out, _ = ran
    from open_guji_cv.steps.free_to_cells import FreeToCellsStep
    col = out["cells"].columns[3].col
    again = FreeToCellsStep().render(ctx, "column_image", column_key(1, col))
    assert np.array_equal(again, ctx.image("column_image", column_key(1, col)))


def test_cell_shrink_on_free(ran):
    _, out, _ = ran
    ci = out["char_index"]
    n = sum(len(cc.chars) for cc in ci.columns)
    assert n == len(out["free_cells"].cells)
    W = out["free_cells"].width
    free = {(c.col, c.order - 1): c for c in out["free_cells"].cells}
    cells = {(cc.col, c.pos, c.sub): c for cc in out["cells"].columns for c in cc.cells}
    near = 0
    for cc in ci.columns:
        for ch in cc.chars:
            f = free[(cc.col, cells[(cc.col, ch.pos, ch.sub)].order)]
            fx = (f.box[0] + f.box[2]) / 2
            bx = (ch.bbox_page[0] + ch.bbox_page[2]) / 2
            near += abs(fx - bx) < 12
    assert near >= 0.95 * n


def test_warp_points_matches_warp_maps(ran):
    _, out, _ = ran
    w = copy.deepcopy(out["layout_blocks"].warp)
    # 弄弯：左边线、上边线加正弦
    for side, amp in (("left", 9.0), ("top", 7.0)):
        t = np.asarray(w["curves"][side]["t"], float)
        w["curves"][side]["p"] = list(np.asarray(w["curves"][side]["p"], float) + amp * np.sin(t / 300.0))
    mx, my = warp_maps(w)
    rng = np.random.default_rng(0)
    ys = rng.integers(0, mx.shape[0], 500)
    xs = rng.integers(0, mx.shape[1], 500)
    px, py = warp_points(w, xs, ys)
    assert np.abs(px - mx[ys, xs]).max() < 1e-2 and np.abs(py - my[ys, xs]).max() < 1e-2


def test_free_mapper_and_grid_rec_unchanged():
    rec = ColumnWindowRec(col=1, left_line=VLineRec(x_at_top=10, slope=0), right_line=VLineRec(x_at_top=0, slope=0),
                          top_y=0, bottom_y=10, border_top_y=0, border_bottom_y=10, border_top_in_column=0,
                          border_bottom_in_column=10, warped_size=(10, 10), side_floor=0.0)
    assert "free_map" not in rec.model_dump(mode="json")       # 格网列窗落盘不变
    assert not isinstance(ColumnMapper.of(100, rec), FreeColumnMapper)
    fm = {"xa": 20, "y0": 5, "h": 4, "w": 6, "rows": [[0, 0], [2, 3]], "warp": None}
    m = ColumnMapper.of(100, rec.model_copy(update={"free_map": fm}))
    assert isinstance(m, FreeColumnMapper)
    assert m.to_page_tl(1, 0) == (21.0, 5.0)
    assert m.to_page_tl(1, 3) == (24.0, 8.0)
    assert m.to_page_tr(1, 3) == (75.0, 8.0)
