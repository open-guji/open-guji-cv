"""通用 IDS 判法（`groups/ids_generic`）：自己造图，不依赖真书数据。"""
import numpy as np

from open_guji_cv.groups import ids_generic as G
from open_guji_cv.groups.ids_plan import derive_plan


def _glyph(right: str, gap_x: int = 46) -> np.ndarray:
    """左边一块实心（余 的替身），右边：`bar` 三条横（又 的替身）或 `col` 两根竖（攵 的替身）；两部件之间空 `gap_x` 附近一列。"""
    g = np.full((100, 100), 255, np.uint8)
    g[10:90, 8:gap_x - 4] = 0
    if right == "bar":
        for y in (25, 45, 65):
            g[y:y + 6, gap_x + 4:92] = 0
    else:
        g[10:90, gap_x + 8:gap_x + 14] = 0
        g[10:90, gap_x + 30:gap_x + 36] = 0
    return g


def test_mean_shape_and_prior_seam_follow_gap():
    shape = G.mean_shape([[[0.5, 0.0], [0.5, 1.0]], [[0.4, 0.0], [0.4, 1.0]]], "v")
    assert len(shape) == G.N_SHAPE and abs(shape[0] - 0.45) < 1e-6
    pl = G.prior_seam(_glyph("bar", gap_x=50), shape, "v")
    xs = [p[0] for p in pl]
    assert all(0.43 <= x <= 0.56 for x in xs)                  # 落在两部件之间的空白里
    assert G.prior_seam(np.full((50, 50), 255, np.uint8), shape, "v") is None


def test_leaf_and_choose_by_form():
    plan = derive_plan("叙敘", "config/groups/xu")
    assert G.usable(plan) and plan.orient == "v" and plan.diff == (1,)
    shape = [0.5] * G.N_SHAPE
    bank = {f: [G.leaf_of(plan, img, G.cut(plan, img, shape))] for f, img in (("叙", _glyph("bar")), ("敘", _glyph("col")))}
    for f, kind in (("叙", "bar"), ("敘", "col")):
        img = _glyph(kind, gap_x=48)
        best, m, _ = G.choose(G.leaf_of(plan, img, G.cut(plan, img, shape)), bank)
        assert best == f and m > 0.05


def test_deep_leaf_cuts_again():
    plan = derive_plan("絕絶", "config/groups/jue")              # 判别叶子 (1,0)：右部上半
    img = np.full((100, 100), 255, np.uint8)
    img[10:90, 8:40] = 0                                       # 左部
    img[10:40, 55:92] = 0                                      # 右上（叶子）
    img[60:90, 55:92] = 0                                      # 右下
    x = G.leaf_of(plan, img, [[0.47, 0.0], [0.47, 1.0]])
    assert x is not None and x.mean() > 0.9                    # 只剩右上那一整块
