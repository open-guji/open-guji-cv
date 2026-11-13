"""impl/keben/row_grid：等距格网的相位与整数格（自造列图）。"""
import numpy as np

from open_guji_cv.impl.keben.row_grid import fit_page_grids


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
    from open_guji_cv.impl.keben.row_boundaries import snap_to_gaps
    proj = np.full(400, 50.0)
    for gap in (95, 212, 300):
        proj[gap - 3:gap + 4] = 0.0
    out = snap_to_gaps(proj, [0.0, 100.0, 200.0, 300.0], 100.0)
    assert len(out) == 4
    assert abs(out[1] - 95) <= 2 and abs(out[2] - 212) <= 2 and abs(out[3] - 300) <= 2


def test_segment_column_with_grid_bounds_skips_dp():
    """给了 grid_bounds 就按它切（落缝后），格数、格号照常，空格照常判空。"""
    from open_guji_cv.impl.keben.row_boundaries import segment_column
    img = _column(blank={20, 21})
    bounds = [40.0 + i * 115.0 for i in range(22)]
    r = segment_column(img, period=115.0, n_body_slots=21, border_top=40.0, border_bottom=40.0 + 21 * 115.0,
                       content_x=(0, img.shape[1]), detect_jiazhu=False, seam_band=0, grid_bounds=bounds)
    assert len(r.boundaries) == 22 and all(abs(a - b) <= 23 for a, b in zip(r.boundaries, bounds))
    kinds = {c.slot: c.kind for c in r.cells}
    assert kinds[1] == "char" and kinds[19] == "char" and kinds[20] == "blank" and kinds[21] == "blank"


# ── grid_end_fit：末线外推到末字墨外沿（2026-11-09，殿本 vol28 列尾下溢）──────────────

def _proj(h, spans, width=100):
    p = np.zeros(h)
    for a, b, v in spans:
        p[a:b] = v
    return p


def test_end_fit_walks_to_frame_line_when_char_sits_on_it():
    from open_guji_cv.impl.keben.row_boundaries import fit_grid_end
    # 末字墨 300–371，紧贴 372–378 的框线（行墨满宽），末线在 340：推到线上沿 372
    p = _proj(400, [(300, 372, 30), (372, 379, 95)])
    assert fit_grid_end(p, [0.0, 340.0], 110.0, hi=390.0, width=100)[-1] == 372.0


def test_end_fit_stops_at_white_gap_and_skips_short_inner_gap():
    from open_guji_cv.impl.keben.row_boundaries import fit_grid_end
    # 末字 300–360，字内 345–347 两行白缝（短于 0.03 格≈3 行），字下 360 起白
    p = _proj(400, [(300, 345, 30), (347, 360, 30)])
    assert fit_grid_end(p, [0.0, 340.0], 110.0, hi=390.0, width=100)[-1] == 360.0


def test_end_fit_keeps_line_when_char_inside_or_no_white_within_reach():
    from open_guji_cv.impl.keben.row_boundaries import fit_grid_end
    # 末线下就是白（字没出格）：不动
    p = _proj(400, [(250, 330, 30)])
    assert fit_grid_end(p, [0.0, 340.0], 110.0, hi=390.0, width=100)[-1] == 340.0
    # 墨一路连到版框外、0.35 格内找不到白行也没碰到框线：不动
    p = _proj(500, [(300, 500, 30)])
    assert fit_grid_end(p, [0.0, 340.0], 110.0, hi=480.0, width=100)[-1] == 340.0
    # 只动末线
    p = _proj(400, [(0, 20, 30), (300, 372, 30), (372, 379, 95)])
    assert fit_grid_end(p, [10.0, 200.0, 340.0], 110.0, hi=390.0, width=100)[:2] == [10.0, 200.0]


def test_end_fit_ignores_frame_junk_below_blank_last_cell():
    from open_guji_cv.impl.keben.row_boundaries import fit_grid_end
    # 末格空（末线上方白），末线下是断续斜框线渣（不到满宽）：不动，免得把框线收成字
    p = _proj(450, [(200, 300, 30), (345, 380, 40)])
    assert fit_grid_end(p, [0.0, 340.0], 110.0, hi=420.0, width=100)[-1] == 340.0


# ── snap_cut：按墨块切割量补挪格线（2026-11-13，史記 r54 少见字页劈字）──────────────

def test_cut_cost_profile_counts_smaller_half_of_split_components():
    from open_guji_cv.seg.seam import cut_cost_profile
    ink = np.zeros((100, 20), bool)
    ink[10:40, 5:15] = True          # 一块 30 行×10 列
    ink[45:50, 5:15] = True          # 另一块，与上一块不连
    c = cut_cost_profile(ink)
    assert len(c) == 101 and c[0] == 0 and c[100] == 0
    assert c[42] == 0 and c[10] == 0 and c[40] == 0     # 两块之间、块的上下沿都不劈
    assert c[20] == 100 and c[25] == 150                 # 线上 10 行×10＝100；正中 150
    assert c[47] == 20                                   # 小块被劈：较小一截 2 行
    assert cut_cost_profile(ink, max_h=20)[25] == 0      # 太高的块不算（界行残段）


def _two_chars_uneven(h=400, w=100):
    """三个字：0–90、130–260（大字，伸出名义格）、300–380，字间白缝；名义格线 0、110、220、330、400。
    220 那条在大字中间，最近的字缝 260–300 离它 40–80 行（> 0.2 格高 22 行，`snap_to_gaps` 够不着）。"""
    img = np.full((h, w), 255, np.uint8)
    for a, b in ((0, 90), (130, 260), (300, 380)):
        img[a:b, 20:80] = 0
    return img


def test_snap_by_cut_moves_line_out_of_char_within_range():
    from open_guji_cv.impl.keben.row_boundaries import row_ink_projection, snap_by_cut, snap_to_gaps
    from open_guji_cv.seg.seam import cut_cost_profile
    img = _two_chars_uneven()
    rp = row_ink_projection(img)
    cut = cut_cost_profile(img < 128)
    nominal = [0.0, 110.0, 220.0, 330.0, 400.0]
    snapped = snap_to_gaps(rp, nominal, 110.0)
    assert 130 < snapped[2] < 260                         # 旧法：停在大字里
    out = snap_by_cut(cut, rp, nominal, snapped, 110.0, 0.4)
    assert 260 <= out[2] <= 300                           # 挪进字缝
    assert out[0] == snapped[0] and out[-1] == snapped[-1]   # 首末线不动
    assert out[1] == snapped[1]                           # 本来在缝里的线不动
    # 范围不够（±0.2 格）就不挪
    assert snap_by_cut(cut, rp, nominal, snapped, 110.0, 0.2)[2] == snapped[2]
    # 护栏不许就不挪
    assert snap_by_cut(cut, rp, nominal, snapped, 110.0, 0.4, gap_ok=lambda *a: False)[2] == snapped[2]


def test_segment_column_snap_cut_off_is_unchanged():
    from open_guji_cv.impl.keben.row_boundaries import segment_column
    img = _two_chars_uneven()
    kw = dict(period=110.0, n_body_slots=4, border_top=0.0, border_bottom=399.0, content_x=(0, 100),
              grid_bounds=[0.0, 110.0, 220.0, 330.0, 399.0], detect_jiazhu=False)
    off = segment_column(img, **kw).boundaries
    on = segment_column(img, snap_cut=0.4, **kw).boundaries
    assert off == segment_column(img, snap_cut=0.0, **kw).boundaries
    assert 130 < off[2] < 260 and 260 <= on[2] <= 300


def test_cut_cost_sides_split_by_minor_part():
    from open_guji_cv.seg.seam import cut_cost_profile, cut_cost_sides
    ink = np.zeros((100, 20), bool)
    ink[10:40, 5:15] = True
    up, dn = cut_cost_sides(ink)
    assert np.array_equal(up + dn, cut_cost_profile(ink))
    assert up[15] == 50 and dn[15] == 0          # 线在 15：小截在上
    assert dn[35] == 50 and up[35] == 0          # 线在 35：小截在下
    assert up[25] == dn[25] == 75                # 正中各半


def test_snap_by_cut_moves_only_toward_minor_part():
    """上下结构的字：线切在字脚（小截在下），往上近处有字内白缝（宀｜貫）、往下稍远才是字缝——只许往下。"""
    from open_guji_cv.impl.keben.row_boundaries import row_ink_projection, snap_by_cut
    from open_guji_cv.seg.seam import cut_cost_sides
    img = np.full((400, 100), 255, np.uint8)
    img[0:80, 20:80] = 0                 # 上一字
    img[150:195, 20:80] = 0              # 宀
    img[200:230, 20:80] = 0              # 貫的上半（宽）
    img[230:272, 44:56] = 0              # 貫的字脚（窄、长），与上半连着
    img[310:380, 20:80] = 0              # 下一字
    rp = row_ink_projection(img)
    sides = cut_cost_sides(img < 128)
    cut = sides[0] + sides[1]
    bounds = [0.0, 100.0, 230.0, 390.0]
    snapped = [0.0, 100.0, 236.0, 390.0]
    plain = snap_by_cut(cut, rp, bounds, snapped, 110.0, 0.4)
    assert 195 <= plain[2] <= 200                         # 不看方向：就近挪进宀｜貫
    out = snap_by_cut(cut, rp, bounds, snapped, 110.0, 0.4, sides=sides)
    assert 272 <= out[2] <= 310                           # 只往小截那边：挪到字脚下
