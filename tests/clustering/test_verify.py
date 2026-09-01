"""verify.py 单测 —— 保守聚类核心判据的行为契约。

- 同图 / 平移扰动 / 轻磨损 → same
- 差异大的字形 → diff
- "一笔之差"（局部集中差异）→ 不得判 same（形近字防线）
"""

import random

import cv2
import numpy as np

from open_guji_cv.clustering.synth import degrade, synthetic_glyph
from open_guji_cv.clustering.verify import verify_pair


def test_identical_is_same():
    g = synthetic_glyph(random.Random(1))
    v = verify_pair(g, g)
    assert v.verdict == "same"
    assert v.f1 == 1.0


def test_translated_is_same():
    g = synthetic_glyph(random.Random(2))
    shifted = np.roll(g, shift=(2, -3), axis=(0, 1))
    v = verify_pair(g, shifted)
    assert v.verdict == "same"
    assert v.f1 > 0.95


def test_worn_copy_is_same():
    """同一字形 + 轻度磨损（同版同字的不同印次）→ same。"""
    rng = random.Random(3)
    base = synthetic_glyph(rng)
    worn = degrade(base, rng, wear=0.3)
    v = verify_pair(base, worn)
    assert v.verdict == "same", f"f1={v.f1:.3f} blob={v.diff_blob_ratio:.3f}"


def test_different_glyphs_not_same():
    """不同随机字形 → 不得 same（保守性）。"""
    for seed in range(10):
        a = synthetic_glyph(random.Random(seed))
        b = synthetic_glyph(random.Random(seed + 1000))
        v = verify_pair(a, b)
        assert v.verdict != "same", f"seed={seed} f1={v.f1:.3f}"


def test_one_stroke_difference_not_same():
    """形近字防线：整体几乎一致但多一笔 → 不得 same。

    模拟"曰/日""大/太"式一笔之差。
    """
    base = synthetic_glyph(random.Random(7))
    extra = base.copy()
    # 在空白处加一小笔（3×6 实心块，远大于噪声）
    ys, xs = np.nonzero(base == 0)
    cv2.rectangle(extra, (8, 8), (16, 12), 1, -1)
    v = verify_pair(base, extra)
    assert v.verdict != "same", \
        f"f1={v.f1:.3f} blob_ratio={v.diff_blob_ratio:.3f}"


def test_empty_patch_is_diff():
    g = synthetic_glyph(random.Random(9))
    empty = np.zeros_like(g)
    assert verify_pair(g, empty).verdict == "diff"
    assert verify_pair(empty, empty).verdict == "diff"


def test_verdict_fields_populated():
    g = synthetic_glyph(random.Random(11))
    v = verify_pair(g, np.roll(g, 1, axis=0))
    assert 0.0 <= v.f1 <= 1.0
    assert v.dilated_f1 >= v.f1 - 1e-9
    assert isinstance(v.shift, tuple)
