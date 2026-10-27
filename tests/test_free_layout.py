"""自由版式管线 keben_free（block_detect → column_trace → cell_cut）在合成页上的行为。

合成页：四周粗框＋一条分栏横线，上下两块各 10 列；每列「3 个大字 → 5 对双行小注 → 2 个大字」。
大字是 100 见方的「丰」形（中段有墨），小注是两个 42 见方的小字并排、中间留缝。
"""

from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册 Step
from tests.helpers import make_book, make_ctx, run_steps

W, H = 1600, 2800
FRAME = (100, 150, 1500, 2700)        # x0, y0, x1, y1（框线中心）
DIV_Y = 900
PITCH = 130


def _glyph(img, x0, y0, s):
    """s 见方的「丰」：三横一竖，横画之间留白（字内缝）。"""
    t = max(3, s // 12)
    for k in range(3):
        y = y0 + int((k + 0.5) * s / 3) - t // 2
        img[y:y + t, x0:x0 + s] = 20
    img[y0:y0 + s, x0 + s // 2 - t // 2:x0 + s // 2 + t // 2 + 1] = 20


def _column(img, xr, y0, y1):
    """一列（右沿 xr）：3 大字、5 对小注、2 大字，自上而下。返回 (大字数, 小注对数)。"""
    y = y0 + 20
    xb = xr - 15 - 100
    n_big = n_note = 0
    for _ in range(3):
        if y + 100 > y1:
            break
        _glyph(img, xb, y, 100); y += 115; n_big += 1
    for _ in range(5):
        if y + 42 > y1:
            break
        _glyph(img, xr - 15 - 42, y, 42)          # 右线
        _glyph(img, xr - 15 - 100, y, 42)         # 左线（中间留 16px 缝）
        y += 52; n_note += 1
    for _ in range(2):
        if y + 100 > y1:
            break
        _glyph(img, xb, y, 100); y += 115; n_big += 1
    return n_big, n_note


def synth_free_page():
    img = np.full((H, W), 225, np.uint8)
    x0, y0, x1, y1 = FRAME
    img[y0 - 8:y0 + 8, x0 - 8:x1 + 8] = 25
    img[y1 - 8:y1 + 8, x0 - 8:x1 + 8] = 25
    img[y0 - 8:y1 + 8, x0 - 8:x0 + 8] = 25
    img[y0 - 8:y1 + 8, x1 - 8:x1 + 8] = 25
    img[DIV_Y - 5:DIV_Y + 5, x0:x1] = 25
    expect = []
    for top, bot in ((y0 + 15, DIV_Y - 15), (DIV_Y + 15, y1 - 15)):
        for c in range(10):
            expect.append(_column(img, x1 - 20 - c * PITCH, top, bot))
    return img, expect


@pytest.fixture
def ran(tmp_path):
    img, expect = synth_free_page()
    ctx = make_ctx(tmp_path, make_book("tfree", pipeline="keben_free"), raw={1: img})
    out = run_steps(ctx, 1, ["block_detect", "column_trace", "cell_cut"])
    return ctx, out, expect


def test_blocks_split_by_divider(ran):
    _, out, _ = ran
    lb = out["layout_blocks"]
    assert lb.page_type == "body"
    assert [b.kind for b in lb.blocks] == ["text", "text"]
    # 读序：上块在前；分栏线在两块之间
    assert lb.blocks[0].box[3] < DIV_Y < lb.blocks[1].box[1]


def test_columns_found_without_rules(ran):
    _, out, _ = ran
    fc = out["free_columns"]
    assert [b.n for b in fc.blocks] == [10, 10]
    assert [c.col for c in fc.columns] == list(range(1, 21))
    # 第 1 列在最右：右上原点下它的右缝 x_tr 最小
    assert fc.columns[0].right[0] < fc.columns[1].right[0]


def test_cells_big_and_notes(ran):
    _, out, expect = ran
    cells = out["free_cells"].cells
    ok = 0
    for col, (n_big, n_note) in enumerate(expect, start=1):
        mine = [c for c in cells if c.col == col]
        kinds = [c.kind for c in mine]
        if (kinds.count("char") == n_big and kinds.count("jiazhu_a") == n_note
                and kinds.count("jiazhu_b") == n_note):
            ok += 1
    assert ok >= 18, f"逐列全对 {ok}/20"


def test_note_reading_order_right_line_first(ran):
    _, out, _ = ran
    col1 = [c for c in out["free_cells"].cells if c.col == 1]
    kinds = [c.kind for c in sorted(col1, key=lambda c: c.order)]
    a, b = kinds.index("jiazhu_a"), kinds.index("jiazhu_b")
    assert a < b


def test_hint_skip_and_cols(tmp_path):
    img, _ = synth_free_page()
    book = make_book("tfree", pipeline="keben_free",
                     layout_hints={"1": "skip", "2": {"cols": [9, None]}})
    ctx = make_ctx(tmp_path, book, raw={1: img, 2: img})
    out = run_steps(ctx, 1, ["block_detect", "column_trace", "cell_cut"])
    assert out["layout_blocks"].page_type == "skip"
    assert out["free_cells"].cells == []
    out = run_steps(ctx, 2, ["block_detect", "column_trace"])
    assert [b.n for b in out["free_columns"].blocks] == [9, 10]
    assert out["free_columns"].blocks[0].n_source == "hint"


def test_hint_manual_box(tmp_path):
    img, _ = synth_free_page()
    x0, y0, x1, _ = FRAME
    book = make_book("tfree", pipeline="keben_free",
                     layout_hints={"1": {"blocks": [{"box": [x0 + 10, y0 + 10, x1 - 10, DIV_Y - 10], "cols": 10}]}})
    ctx = make_ctx(tmp_path, book, raw={1: img})
    out = run_steps(ctx, 1, ["block_detect", "column_trace"])
    assert [b.source for b in out["layout_blocks"].blocks] == ["hint"]
    assert [b.n for b in out["free_columns"].blocks] == [10]


def test_parse_hints_rejects_bad_shape():
    from open_guji_cv.utils.layout_hints import parse_layout_hints
    with pytest.raises(ValueError):
        parse_layout_hints({"3": {"type": "picture"}})
    with pytest.raises(ValueError):
        parse_layout_hints({"3": {"blocks": [{"box": [1, 2, 3, 4]}, {"cols": 3}]}})
    h = parse_layout_hints({"5-7": "skip", "9": {"cols": 12}})
    assert sorted(h) == [5, 6, 7, 9] and h[6].type == "skip" and h[9].cols_for(1) == 12


def test_pipeline_selected_by_book_field():
    from open_guji_cv.core.pipeline import default_pipeline_id
    assert default_pipeline_id(make_book("x", pipeline="keben_free")) == "keben_free"
    assert default_pipeline_id(make_book("x")) == "keben_body_v2"
