"""books/siku_zongmu/row_grid：等距格网的相位与整数格（自造列图）。"""
import numpy as np

from open_guji_cv.books.siku_zongmu.row_grid import fit_page_grids


def _column(h=2500, w=120, top=40.0, pitch=115.0, n=21, blank=(), offset=0.0, bar=None):
    """白底列图：第 i 格（1 起）在 top+(i-1)·pitch 处画一个 0.7 格高的黑块（字）；blank 里的格不画。
    offset 把整列墨往下挪（模拟列图起点不齐）。bar=(y0, y1) 在那里加一大片墨（印章）。"""
    img = np.full((h, w), 255, np.uint8)
    for i in range(1, n + 1):
        if i in blank:
            continue
        y0 = int(top + offset + (i - 1) * pitch + 0.15 * pitch)
        img[y0:y0 + int(0.7 * pitch), 20:w - 20] = 0
    if bar is not None:
        img[bar[0]:bar[1], 10:w - 10] = 0
    return img


def _col(k, img, bt=40.0, bb=40.0 + 21 * 115.0):
    return dict(col=k, img=img, content_x=(0, img.shape[1]), border_top=bt, border_bottom=bb, n_raised=0)


def _assert_on_grid(g, top, pitch, tol=6.0):
    b = g.bounds(21, 0)
    assert len(b) == 22
    assert all(abs(y - (top + i * pitch)) <= tol for i, y in enumerate(b)), b[:3]


def test_grid_follows_ink_phase_per_column():
    # 三列列图起点各差 0.3 格：每列格线跟着自己的墨走，格号不乱
    cols = [_col(k, _column(offset=d)) for k, d in ((1, 0.0), (2, 0.3 * 115), (3, -0.3 * 115))]
    g = fit_page_grids(cols, period=115.0)
    for k, d in ((1, 0.0), (2, 0.3 * 115), (3, -0.3 * 115)):
        _assert_on_grid(g[k], 40.0 + d, 115.0, tol=8.0)


def test_blank_and_seal_cells_keep_slots():
    # 列首两格空、压一方印章；列尾三格空：格线照样等距，不被印章和空白带偏
    cols = [_col(1, _column()), _col(2, _column()),
            _col(3, _column(blank={1, 2, 19, 20, 21}, bar=(60, 250)))]
    g = fit_page_grids(cols, period=115.0)
    _assert_on_grid(g[3], 40.0, 115.0, tol=8.0)


def test_pitch_is_searched_around_period():
    cols = [_col(k, _column(pitch=118.0), bb=40.0 + 21 * 118.0) for k in (1, 2, 3)]
    g = fit_page_grids(cols, period=115.0)
    assert abs(g[1].pitch - 118.0) < 0.6
    _assert_on_grid(g[1], 40.0, 118.0, tol=8.0)


def test_snap_moves_each_line_into_nearest_gap():
    """等距格线各自在 ±0.2 格内挪进字缝；缝不在范围内就留在行墨最少处，格数不变。"""
    from open_guji_cv.books.siku_zongmu.row_boundaries import snap_to_gaps
    proj = np.full(400, 50.0)
    for gap in (95, 212, 300):
        proj[gap - 3:gap + 4] = 0.0
    out = snap_to_gaps(proj, [0.0, 100.0, 200.0, 300.0], 100.0)
    assert len(out) == 4
    assert abs(out[1] - 95) <= 2 and abs(out[2] - 212) <= 2 and abs(out[3] - 300) <= 2


def test_segment_column_with_grid_bounds_skips_dp():
    """给了 grid_bounds 就按它切（落缝后），格数、格号照常，空格照常判空。"""
    from open_guji_cv.books.siku_zongmu.row_boundaries import segment_column
    img = _column(blank={20, 21})
    bounds = [40.0 + i * 115.0 for i in range(22)]
    r = segment_column(img, period=115.0, n_body_slots=21, border_top=40.0, border_bottom=40.0 + 21 * 115.0,
                       content_x=(0, img.shape[1]), detect_jiazhu=False, seam_band=0, grid_bounds=bounds)
    assert len(r.boundaries) == 22 and all(abs(a - b) <= 23 for a, b in zip(r.boundaries, bounds))
    kinds = {c.slot: c.kind for c in r.cells}
    assert kinds[1] == "char" and kinds[19] == "char" and kinds[20] == "blank" and kinds[21] == "blank"
