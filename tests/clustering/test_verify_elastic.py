"""verify_pair_elastic 单测：软覆盖 + 分块弹性对齐的判据契约。

判据的两条设计主张各有一条测试钉住：
1. **局部位移由分块弹性吸收**——同字的逐部件刻痕位移仍判 same；
2. **距离容忍是软的**——多/少一笔的残差不再被硬膨胀抹平，形近护栏拦得住。
另加校准契约：分数读在 coverage 的刻度上（单调、[0,1]、满分 1.0）。
"""

import random

import numpy as np

from open_guji_cv.clustering.synth import degrade, synthetic_glyph
from open_guji_cv.clustering.verify import (ELASTIC_COV_HIGH, ELASTIC_LOCAL,
                                            _calibrate, _CAL_COV, _CAL_RAW,
                                            verify_pair_elastic)


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
    v = verify_pair_elastic(a, a)
    assert v.verdict == "same" and v.f1 == 1.0


def test_local_carving_jitter_is_same():
    """同字位移：下半整体挪 2px。全局刚性对齐吃不下，分块弹性必须吃下。"""
    a = _glyph()
    b = a.copy()
    b[33:, :] = 0
    b[35:, 2:] = a[33:-2, :-2]
    assert verify_pair_elastic(a, b).verdict == "same", verify_pair_elastic(a, b)


def test_wear_degradation_is_not_diff():
    a = _glyph()
    b = degrade(a, random.Random(2), wear=0.25)
    assert verify_pair_elastic(a, b).verdict in ("same", "unsure")


def test_extra_stroke_is_blocked():
    """多一笔（太/大 式）：软覆盖不给它满分，窗口残差也拦得住 → 不得 same。"""
    a = _glyph()
    b = a.copy()
    b[8:12, 20:44] = 1
    v = verify_pair_elastic(a, b)
    assert v.verdict != "same"


def test_unrelated_shapes_are_diff():
    a = _glyph(1)
    b = np.zeros_like(a)
    b[10:54, 30:34] = 1
    assert verify_pair_elastic(a, b).verdict == "diff"


def test_empty_patch_is_diff():
    a = _glyph()
    assert verify_pair_elastic(a, np.zeros_like(a)).verdict == "diff"


def test_shift_field_matches_coverage_convention():
    """shift 与 coverage 同约定（把 b 摆回 a 上，符号不能反）。

    报告出来的是**全局刚性那一份**：块内还能再走 ±ELASTIC_LOCAL，所以
    真实位移 = shift ± local，这里按这个契约留容差。
    """
    a = _glyph(3)
    b = np.zeros_like(a)
    b[2:, 2:] = a[:-2, :-2]                   # b = a 右下平移 2px
    v = verify_pair_elastic(a, b)
    assert abs(v.shift[0] - 2) <= ELASTIC_LOCAL, v.shift
    assert abs(v.shift[1] - 2) <= ELASTIC_LOCAL, v.shift
    assert v.verdict == "same"


def test_calibration_is_monotone_and_bounded():
    """校准表必须严格单调、把 [0,1] 映到 [0,1]——排序不能被压平。"""
    assert list(_CAL_RAW) == sorted(set(_CAL_RAW))
    assert list(_CAL_COV) == sorted(set(_CAL_COV))
    assert _calibrate(0.0, _CAL_RAW, _CAL_COV) == 0.0
    assert _calibrate(1.0, _CAL_RAW, _CAL_COV) == 1.0
    xs = np.linspace(0.0, 1.0, 101)
    ys = [_calibrate(float(x), _CAL_RAW, _CAL_COV) for x in xs]
    assert all(y2 > y1 for y1, y2 in zip(ys, ys[1:]))


def test_cov_high_gate_is_the_elastic_one():
    """默认闸走 elastic 自己的标定值，不借 coverage 的 0.992。"""
    a = _glyph(4)
    b = degrade(a, random.Random(5), wear=0.05)
    v = verify_pair_elastic(a, b, cov_high=ELASTIC_COV_HIGH)
    assert (v.f1 >= ELASTIC_COV_HIGH) == (v.verdict == "same"
                                          or v.diff_blob_ratio > 12)
