"""normalize.py 单测：归一化的平移/尺度不变性与空图处理。"""

import random

import numpy as np

from open_guji_cv.clustering.normalize import (NORM_SIZE, ink_bbox,
                                               normalize_patch,
                                               sauvola_binarize)
from open_guji_cv.clustering.synth import synthetic_glyph


def _to_gray(binary: np.ndarray, canvas: int = 100,
             offset: tuple[int, int] = (10, 10)) -> np.ndarray:
    """二值字形放到大灰度画布上（白底黑字）。"""
    gray = np.full((canvas, canvas), 230, dtype=np.uint8)
    h, w = binary.shape
    y, x = offset
    region = gray[y:y + h, x:x + w]
    region[binary > 0] = 25
    return gray


def test_output_shape_and_dtype():
    glyph = synthetic_glyph(random.Random(1))
    out = normalize_patch(_to_gray(glyph))
    assert out.shape == (NORM_SIZE, NORM_SIZE)
    assert out.dtype == np.uint8
    assert set(np.unique(out)).issubset({0, 1})


def test_empty_patch_returns_zeros():
    gray = np.full((80, 60), 240, dtype=np.uint8)
    out = normalize_patch(gray)
    assert not out.any()


def test_translation_invariance():
    """同一字形放在画布不同位置，归一化结果应几乎一致。"""
    glyph = synthetic_glyph(random.Random(2))
    a = normalize_patch(_to_gray(glyph, offset=(5, 5)))
    b = normalize_patch(_to_gray(glyph, offset=(25, 20)))
    inter = np.count_nonzero(a & b)
    union = np.count_nonzero(a | b)
    assert inter / union > 0.9


def test_scale_invariance():
    """同一字形不同缩放，归一化后应高度重叠。"""
    import cv2
    glyph = synthetic_glyph(random.Random(3))
    big = cv2.resize(glyph * 255, (120, 120), interpolation=cv2.INTER_NEAREST)
    big = (big > 127).astype(np.uint8)
    a = normalize_patch(_to_gray(glyph, canvas=110))
    b = normalize_patch(_to_gray(big, canvas=160))
    inter = np.count_nonzero(a & b)
    union = np.count_nonzero(a | b)
    assert inter / union > 0.75


def test_sauvola_dark_text_on_light():
    gray = np.full((50, 50), 220, dtype=np.uint8)
    gray[20:30, 10:40] = 30
    binary = sauvola_binarize(gray)
    assert binary[25, 25] == 1
    assert binary[5, 5] == 0


def test_ink_bbox():
    img = np.zeros((10, 10), dtype=np.uint8)
    assert ink_bbox(img) is None
    img[2:5, 3:7] = 1
    assert ink_bbox(img) == (3, 2, 7, 5)
