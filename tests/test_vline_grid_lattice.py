"""网格模式「版框对不在候选池」时的网格反推（`lattice_frame_pair`，殿本换源 vol12 p139，GUJI-748）。

那一页右版框贴图边、被边窗里的界行顶掉，候选池里没有版框对，`select_frame_pair` 返回 None，
网格模式退回截断、与自由模式逐条相同。`lattice_fallback=True` 时改按细界行拟等距网格反推两端。
"""
import numpy as np

import open_guji_cv.utils.peak_line_search as P
from open_guji_cv.utils.peak_line_search import LineMatch, find_vertical_lines_grid, lattice_frame_pair

H, W = 600, 1400
PITCH = 133.0
X0 = 60.0
N_LINES = 10
XS = [X0 + k * PITCH for k in range(N_LINES)]       # 60 .. 1257


def _mask(skip=()):
    m = np.zeros((H, W), dtype=np.float64)
    for k, x in enumerate(XS):
        if k in skip:
            continue
        xi = int(round(x))
        m[30:H - 30, xi - 1:xi + 2] = 1.0
    return m


def _thin(x):
    return LineMatch(position=float(x), slope=0.0, score=300.0, width=4.0, proj=500.0)


def _pool(ks, extra=()):
    return [_thin(XS[k]) for k in ks] + list(extra)


def test_lattice_recovers_both_frames_from_inner_rules():
    """池里缺右框（k=9）和一条界行（k=6），另有一条宽假峰；两端精搜都搜到实线。"""
    fake = LineMatch(position=XS[8] + 66, slope=0.0, score=18.0, width=60.0, proj=900.0)
    got = lattice_frame_pair(_mask(), _pool([0, 1, 2, 3, 4, 5, 7, 8], [fake]), N_LINES, PITCH)
    assert got is not None
    a, b, af, bf = got
    assert abs(a.position - XS[0]) <= 2 and abs(b.position - XS[9]) <= 2
    assert (af, bf) == (False, False)


def test_lattice_marks_endpoint_filled_when_no_line_printed():
    m = _mask(skip={9})
    a, b, af, bf = lattice_frame_pair(m, _pool([0, 1, 2, 3, 4, 5, 7, 8]), N_LINES, PITCH)
    assert not af and bf
    assert abs(b.position - XS[9]) <= 2 and b.score == 0.0


def test_lattice_refuses_ambiguous_window():
    """图够宽、几个 10 槽窗口支持一样多、两端都没支持线：不猜，返回 None。"""
    wide = np.zeros((H, 1600), dtype=np.float64)
    ks = [3, 4, 5, 6, 7]
    assert lattice_frame_pair(wide, _pool(ks), N_LINES, PITCH) is None


def test_lattice_refuses_thin_support():
    assert lattice_frame_pair(_mask(), _pool([3, 4]), N_LINES, PITCH) is None


def test_grid_lattice_fallback_only_when_asked(monkeypatch):
    """选不出版框对时：缺省仍是截断（加开关前的行为），开了才走网格反推、出满 10 条。"""
    m = _mask()
    pool = _pool([0, 1, 2, 3, 4, 5, 7, 8])
    monkeypatch.setattr(P, "_vline_pool", lambda *a, **k: (list(pool), None))
    monkeypatch.setattr(P, "select_frame_pair", lambda *a, **k: None)
    off, off_f = find_vertical_lines_grid(m, N_LINES, PITCH)
    assert len(off) == 8 and not any(off_f)
    on, on_f = find_vertical_lines_grid(m, N_LINES, PITCH, lattice_fallback=True)
    assert len(on) == N_LINES
    for ln, x in zip(on, XS):
        assert abs(ln.position - x) <= 2
    assert not any(on_f)                       # k=6 那条精搜验上了，不是插值


def test_grid_lattice_fallback_needs_col_pitch(monkeypatch):
    pool = _pool([0, 1, 2, 3, 4, 5, 7, 8])
    monkeypatch.setattr(P, "_vline_pool", lambda *a, **k: (list(pool), None))
    monkeypatch.setattr(P, "select_frame_pair", lambda *a, **k: None)
    lines, _ = find_vertical_lines_grid(_mask(), N_LINES, None, lattice_fallback=True)
    assert len(lines) == 8
