"""verify_pair_cov 单测：覆盖率判据的三档语义与形近护栏。

设计依据（g3g4_error_analysis.md）：同字 = 同一字的不同手工雕刻，带 2~3px
局部笔画位移；形近 = 多/少/换一笔，残差在 12×12 窗口里是集中的。
"""

import random

import numpy as np

from open_guji_cv.clustering.synth import degrade, synthetic_glyph
from open_guji_cv.clustering.verify import verify_pair_cov


def _pad(g, size=64):
    out = np.zeros((size, size), dtype=np.uint8)
    h, w = g.shape
    y, x = (size - h) // 2, (size - w) // 2
    out[y:y + h, x:x + w] = g
    return out


def _glyph(seed=1):
    return _pad(synthetic_glyph(random.Random(seed)))


def test_identical_is_same():
    a = _glyph()
    v = verify_pair_cov(a, a)
    assert v.verdict == "same" and v.f1 == 1.0


def test_local_carving_jitter_is_same():
    """同字位移：把字的下半整体挪 2px——刻工位移的典型形态，必须 same。

    这正是旧 overlap 判据打不过的场景（全局配准只能全体一起移）。
    """
    a = _glyph()
    b = a.copy()
    b[33:, :] = 0
    b[35:, 2:] = a[33:-2, :-2]
    v = verify_pair_cov(a, b)
    assert v.verdict == "same", v


def test_wear_degradation_is_not_diff():
    a = _glyph()
    b = degrade(a, random.Random(2), wear=0.25)
    assert verify_pair_cov(a, b).verdict in ("same", "unsure")


def test_extra_stroke_is_blocked_by_window_guard():
    """多一笔（太/大 式）：覆盖率还很高，但 12×12 窗口残差超限 → 不得 same。"""
    a = _glyph()
    b = a.copy()
    b[8:12, 20:44] = 1                       # 顶部加一条 4×24 的横笔
    v = verify_pair_cov(a, b)
    assert v.verdict != "same"
    assert v.diff_blob_ratio > 12            # 该字段在 cov 判据下放窗口残差


def test_unrelated_shapes_are_diff():
    a = _glyph(1)
    b = np.zeros_like(a)
    b[10:54, 30:34] = 1                      # 一条竖 vs 完整字形
    assert verify_pair_cov(a, b).verdict == "diff"


def test_empty_patch_is_diff():
    a = _glyph()
    assert verify_pair_cov(a, np.zeros_like(a)).verdict == "diff"


def test_fields_carry_cov_and_wmax():
    a = _glyph()
    v = verify_pair_cov(a, a)
    assert 0.0 <= v.f1 <= 1.0                # f1 字段 = 覆盖率
    assert v.diff_blob_ratio == 0.0          # 无残差
