"""`seg.warp` 的 `ruled` 矫正（column_warp 书级开关 `ruled_warp`）：竖向线性、横向逐行插值；逆映射与正向一致。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.seg.frame_types import VLine
from open_guji_cv.seg.warp import warp_column
from open_guji_cv.steps._warpmap import ColumnMapper

W, H = 300, 1000
# 右上原点：右线 x=40 竖直，左线上 120、下 130（列宽上窄下宽 10%，像殿本 Commons 新图）
RIGHT = VLine(x_at_top=40.0, slope=0.0)
LEFT = VLine(x_at_top=120.0, slope=0.01)


def _page_with_stripes(pitch=50):
    img = np.full((H, W), 255, np.uint8)
    for y in range(25, H, pitch):
        img[y:y + 4, :] = 0
    return img


def _stripe_rows(col):
    dark = (col[:, col.shape[1] // 2] < 128).astype(int)
    return [i for i in range(1, len(dark)) if dark[i] and not dark[i - 1]]


def test_ruled_keeps_vertical_spacing_uniform():
    img = _page_with_stripes()
    for det in (False, True):
        col = warp_column(img, LEFT, RIGHT, 0.0, float(H - 1), det=det, ruled=True)
        gaps = np.diff(_stripe_rows(col))
        assert gaps.max() - gaps.min() <= 1          # 纸面等距，列图也等距
        proj = warp_column(img, LEFT, RIGHT, 0.0, float(H - 1), det=det)
        pg = np.diff(_stripe_rows(proj))
        assert pg.max() - pg.min() >= 3              # 射影把梯形当透视，竖向被拉得不匀


def test_ruled_mapper_roundtrip():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (H, W), dtype=np.uint8)
    col = warp_column(img, LEFT, RIGHT, 10.0, 980.0, det=True, ruled=True)
    m = ColumnMapper(W, LEFT, RIGHT, 10.0, 980.0, ruled=True)
    assert (m.out_w, m.out_h) == (col.shape[1], col.shape[0])
    for x, y in [(0, 0), (40, 300), (col.shape[1] - 1, col.shape[0] - 1), (17, 811)]:
        X, Y = m.to_page_tl(x, y)
        assert int(round(Y)) == int(round(10.0 + y * 970.0 / col.shape[0]))
        xi, yi = int(np.floor(X)), int(np.floor(Y))
        if X == xi and Y == yi:
            assert col[y, x] == img[yi, xi]
    # 列图左右边落在两条线上（右上原点 → 左上原点）
    _, Y = m.to_page_tl(0, 500)
    assert abs(m.to_page_tr(0, 500)[0] - LEFT.x_at(Y)) < 1e-6
    assert abs(m.to_page_tr(m.out_w, 500)[0] - RIGHT.x_at(Y)) < 1e-6


def test_ruled_off_by_default_not_dumped():
    from open_guji_cv.products.kinds.columns import ColumnWindowRec
    from open_guji_cv.steps.column_warp import ColumnWarpParams
    assert "ruled_warp" not in ColumnWarpParams().model_dump()
    assert "ruled_warp" in ColumnWarpParams(ruled_warp=True).model_dump()
    assert "ruled" not in ColumnWindowRec.model_fields or ColumnWindowRec.model_fields["ruled"].default is False


def test_colgeom_follows_ruled():
    """人裁切线的页面坐标换算（eval/colgeom）也要认 ruled，否则钉线落错行。"""
    from open_guji_cv.eval.colgeom import ColumnGeom, geom_sig
    m = ColumnMapper(W, LEFT, RIGHT, 10.0, 980.0, ruled=True)
    base = {"left_line": {"x_at_top": LEFT.x_at_top, "slope": LEFT.slope},
            "right_line": {"x_at_top": RIGHT.x_at_top, "slope": RIGHT.slope}, "top_y": 10.0, "bottom_y": 980.0}
    g = ColumnGeom({**base, "ruled": True}, W)
    assert (g.out_w, g.height) == (m.out_w, m.out_h)
    for u, r in [(5.0, 0.0), (40.0, 300.0), (70.0, 900.0)]:
        X, Y = g.row_to_page(r, u)
        assert np.allclose((X, Y), m.to_page_tl(u, r))
        assert np.allclose(g.page_to_row(X, Y), (r, u))
    assert geom_sig(base, W) != geom_sig({**base, "ruled": True}, W)
    assert geom_sig(base, W) == geom_sig({**base, "ruled": False}, W)
