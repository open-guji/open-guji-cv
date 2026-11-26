"""字间界线判官 `impl/keben/boundary_net.refine_bounds`：不加载模型（打分函数换成按图里写死的「真缝」给分），只测重排逻辑。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.impl.keben import boundary_net as bn
from open_guji_cv.impl.keben.row_boundaries import Cell


def _col(blocks, h=700, w=60):
    """白底列图，blocks＝[(y0, y1)] 涂黑的横条（当字）。"""
    img = np.full((h, w), 255, np.uint8)
    for a, b in blocks:
        img[a:b, 10:50] = 0
    return img


def _cells(bounds, kinds=None):
    kinds = kinds or ["char"] * (len(bounds) - 1)
    return [Cell(slot=i + 1, y0=a, y1=b, x0=0, x1=60, kind=k) for i, (a, b, k) in enumerate(zip(bounds, bounds[1:], kinds))]


def _fake_score(true_cuts):
    def f(name, gcol, ys, period):
        return np.array([0.99 if min(abs(y - t) for t in true_cuts) <= 4 else 0.01 for y in ys])
    return f


def test_moves_line_out_of_intra_char_gap(monkeypatch):
    # 字 3 是上下两块（170–200、212–290），现线 206 落在它的字内白缝；真缝在 160
    img = _col([(10, 90), (110, 150), (170, 200), (212, 290), (310, 390), (410, 490)])
    bounds = [5.0, 100.0, 206.0, 300.0, 400.0, 500.0]
    monkeypatch.setattr(bn, "score", _fake_score([100, 160, 300, 400]))
    out = bn.refine_bounds("x", img, (0, 60), _cells(bounds), 100.0, p_old=0.05)
    assert out is not None
    moves, log = out
    assert [j for j, _ in moves] == [1]
    assert abs(moves[0][1] - 160) <= 6


def test_keeps_confident_lines(monkeypatch):
    img = _col([(10, 90), (110, 190), (210, 290), (310, 390), (410, 490)])
    bounds = [5.0, 100.0, 200.0, 300.0, 400.0, 500.0]
    monkeypatch.setattr(bn, "score", _fake_score([100, 200, 300, 400]))
    assert bn.refine_bounds("x", img, (0, 60), _cells(bounds), 100.0, p_old=0.05) is None


def test_skips_columns_with_jiazhu(monkeypatch):
    img = _col([(10, 90), (110, 190), (210, 290), (310, 390), (410, 490)])
    bounds = [5.0, 100.0, 200.0, 300.0, 400.0, 500.0]
    monkeypatch.setattr(bn, "score", _fake_score([]))
    kinds = ["char", "char", "jiazhu_a", "char", "char"]
    assert bn.refine_bounds("x", img, (0, 60), _cells(bounds, kinds), 100.0, p_old=0.05) is None
