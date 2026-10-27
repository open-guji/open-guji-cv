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
    """s 见方的「丰」：三横一竖，横画之间留白（字内缝）。笔画粗约字身 1/8（刻本大字的
    横画比栏线粗得多；各列横画在合成页上齐平，太细会被当成一条浅栏线）。"""
    t = max(3, s // 8)
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


def test_pitch_hint_grid_skips_banxin(tmp_path):
    """书脊一侧（奇数页在左）有浅版心线和几个小字：等宽网格只盖正文 10 列，版心裁出块外。"""
    img, _ = synth_free_page()
    x0, y0, x1, y1 = FRAME
    img[y0:y1, x0 + 55:x0 + 57] = 170                 # 浅：过不了墨阈，只有细竖线图看得见
    for y in (300, 1200, 2000):
        _glyph(img, x0 + 15, y, 30)                   # 版心里的书名、页码
    book = make_book("tfree", pipeline="keben_free", layout_hints={"1-3": {"pitch": 125}},
                     params={"block_detect": {"banxin": "odd_left"}})
    ctx = make_ctx(tmp_path, book, raw={1: img})
    out = run_steps(ctx, 1, ["block_detect", "column_trace"])
    lb, fc = out["layout_blocks"], out["free_columns"]
    assert lb.spine == "left" and lb.banxin is not None
    assert all(b.pitch_hint == 125 for b in lb.blocks)
    assert [b.n for b in fc.blocks] == [10, 10]
    assert {b.n_source for b in fc.blocks} == {"grid"}
    # 每列左右缝夹住该列的字（列 c 的右沿 x1-20-c·PITCH，字在其左 15–115px）
    for c in fc.columns:
        k = (c.col - 1) % 10
        xr_tl = x1 - 20 - k * PITCH
        r_tl = W - 1 - np.median(c.right)
        l_tl = W - 1 - np.median(c.left)
        assert r_tl >= xr_tl - 15 and l_tl <= xr_tl - 115


def test_split_hint_without_rule(tmp_path):
    """分栏没有线：人标大约 y，吸到两栏之间最空的那一行。"""
    img, _ = synth_free_page()
    x0, _, x1, _ = FRAME
    img[DIV_Y - 5:DIV_Y + 5, x0:x1] = 225              # 抹掉分栏线
    book = make_book("tfree", pipeline="keben_free", layout_hints={"1": {"splits": [DIV_Y + 30]}})
    ctx = make_ctx(tmp_path, book, raw={1: img})
    lb = run_steps(ctx, 1, ["block_detect"])["layout_blocks"]
    assert len(lb.blocks) == 2
    assert abs(lb.blocks[0].box[3] - DIV_Y) < 40 and abs(lb.blocks[1].box[1] - DIV_Y) < 40


def test_hints_merge_range_then_page():
    from open_guji_cv.utils.layout_hints import parse_layout_hints
    h = parse_layout_hints({"9": {"cols": [12, None]}, "5-20": {"pitch": 115}, "35-40": {"pitch": [None, 143]}})
    assert h[9].cols_for(0) == 12 and h[9].pitch_for(0) == 115 and h[10].cols_for(0) is None
    assert h[36].pitch_for(0) is None and h[36].pitch_for(1) == 143


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


def _mixed_page():
    """混排（游学鳌头 15b 那种）：下栏右两列一路到底，左边八列再分三层。左边两条横线只盖住下栏宽的约八成。"""
    img, _ = synth_free_page()
    x0, y0, x1, y1 = FRAME
    xv = x1 - 20 - 2 * PITCH + 5                      # 第 2、3 列之间（右两列在右）
    img[DIV_Y + 5:y1, xv - 2:xv + 2] = 25
    ys = (DIV_Y + (y1 - DIV_Y) // 3, DIV_Y + 2 * (y1 - DIV_Y) // 3)
    for y in ys:
        img[y - 2:y + 2, x0:xv] = 25
    return img, xv, ys


def _tl_boxes(lb):
    boxes = [tuple(W - 1 - v if i in (0, 2) else v for i, v in enumerate(b.box)) for b in lb.blocks]
    return [(min(b[0], b[2]), b[1], max(b[0], b[2]), b[3]) for b in boxes]    # 换回左上原点


def test_partial_line_does_not_split_without_hint(tmp_path):
    """没人标时只切首尾贯穿的线：混排页左边的半截横线（约八成宽）不切，免得整栏读序乱。"""
    img, _, _ = _mixed_page()
    ctx = make_ctx(tmp_path, make_book("tfree", pipeline="keben_free"), raw={1: img})
    tl = _tl_boxes(run_steps(ctx, 1, ["block_detect"])["layout_blocks"])
    assert len(tl) == 2 and tl[0][3] < DIV_Y < tl[1][1], tl


def test_tree_hint_splits_mixed_layout(tmp_path):
    """人标版面树：上下 1:2，下栏右 2 列、左 8 列，左边均分 3 层。人给的是约数，切位吸到线上。"""
    img, xv, ys = _mixed_page()
    tree = {"h": [1, 2], "parts": [{"cols": 10}, {"v": [2, 8], "parts": [{"cols": 2}, {"h": 3, "cols": 8}]}]}
    book = make_book("tfree", pipeline="keben_free", layout_hints={"1": {"tree": tree}})
    ctx = make_ctx(tmp_path, book, raw={1: img})
    lb = run_steps(ctx, 1, ["block_detect"])["layout_blocks"]
    tl = _tl_boxes(lb)
    assert len(tl) == 5, tl
    top, right, *left = tl
    assert top[3] < DIV_Y < right[1] and right[0] > xv - 20            # 上栏；下栏右两列
    assert all(b[2] < xv for b in left)                                  # 左边三层，自上而下
    assert left[0][3] < ys[0] < left[1][1] and left[1][3] < ys[1] < left[2][1]
    assert abs(top[3] - DIV_Y) < 20 and abs(left[0][3] - ys[0]) < 20    # 吸到线上，不是按比例的位置
    assert [b.cols_hint for b in lb.blocks] == [10, 2, 8, 8, 8]


def test_tree_hint_rejects_bad_shape():
    from open_guji_cv.utils.layout_hints import parse_layout_hints
    with pytest.raises(ValueError):
        parse_layout_hints({"3": {"tree": {"h": 2, "v": 2}}})
    with pytest.raises(ValueError):
        parse_layout_hints({"3": {"tree": {"h": 2, "parts": [{}, {}, {}]}}})
