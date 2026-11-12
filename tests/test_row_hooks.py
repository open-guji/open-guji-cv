"""Step3 行切分书级钩子（impl/keben/row_hooks）：缺省 None 不调；给了就在对的位置调、按返回值改。"""
import numpy as np

from open_guji_cv.impl.keben import row_hooks
from open_guji_cv.impl.keben.row_boundaries import segment_column

P, N = 60, 21


def _col(blank=(5, 6)):
    img = np.full((P * N + 20, 70), 255, np.uint8)
    for k in range(N):
        if k not in blank:
            y = 10 + k * P
            img[y + 10:y + P - 10, 15:55] = 0
    return img


def _seg(**kw):
    grid = [10.0 + k * P for k in range(N + 1)]
    return segment_column(_col(), float(P), N, border_top=10, border_bottom=10 + N * P, grid_bounds=grid, **kw)


def test_defaults_are_none():
    assert row_hooks.grid_adjust is None and row_hooks.jiazhu_heads is None and row_hooks.half_a_left is None


def test_grid_adjust_identity_keeps_result_and_is_called():
    calls = []

    def ga(row_proj, bounds, period, dst_w):
        calls.append((len(bounds), period))
        return bounds

    assert repr(_seg(grid_adjust=ga)) == repr(_seg())
    assert calls == [(N + 1, float(P))]


def test_grid_adjust_changes_lines():
    def shift(row_proj, bounds, period, dst_w):
        return [b + (8.0 if 0 < i < len(bounds) - 1 else 0.0) for i, b in enumerate(bounds)]

    assert repr(_seg(grid_adjust=shift)) != repr(_seg())
