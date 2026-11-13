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



# 雙行小注：借 test_forced_jiazhu 的合成列（人指认第 8 格是小注，从中缝拆）
from test_forced_jiazhu import COL_W, N_SLOTS, SLOT_H, _cells, _column  # noqa: E402


def _seg_jz(**kw):
    return segment_column(_column(thin_seam_slots=(8,)), period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W,
                          forced_jiazhu={8}, **kw)


def test_pair_ok_default_none():
    assert row_hooks.jiazhu_pair_ok is None


def test_pair_ok_true_keeps_result_and_is_called():
    calls = []

    def ok(patch, ink_threshold, forced):
        calls.append(forced)
        return True

    base = _seg_jz()
    assert sorted(_cells(base)[8]) == ["a", "b"]
    assert repr(_seg_jz(jiazhu_pair_ok=ok)) == repr(base)
    assert True in calls and False in calls      # 人指认的格 forced=True；段里的格收编后再查一次 forced=False


def test_pair_ok_false_on_forced_keeps_whole_char():
    r = _seg_jz(jiazhu_pair_ok=lambda patch, ink_threshold, forced: not forced)
    assert set(_cells(r)[8]) == {""} and _cells(r)[8][""].kind == "char"


def test_pair_ok_false_drops_cell_from_run():
    r = _seg_jz(jiazhu_pair_ok=lambda patch, ink_threshold, forced: forced)
    assert set(_cells(r)[8]) == {""}


def test_jiazhu_heads_gets_ruler():
    got = []

    def heads(entries, runs, patches, eligible=None, ink_threshold=128, ruler=None):
        got.append(ruler)
        return {}

    assert repr(_seg_jz(jiazhu_heads=heads)) == repr(_seg_jz())
    assert got and got[0] == float(COL_W)
