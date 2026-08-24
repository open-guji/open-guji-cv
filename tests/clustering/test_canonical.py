"""canonical.py 单测：统一存储格式的形状/居中/只缩不放/清理/幂等。"""

import random

import cv2
import numpy as np

from open_guji_cv.clustering.canonical import (CANON_MARGIN_RATIO, CANON_SIZE,
                                               canonical_png, is_canonical,
                                               to_canonical)
from open_guji_cv.clustering.synth import synthetic_glyph


def _to_gray(binary: np.ndarray, canvas: int = 120,
             offset: tuple[int, int] = (12, 30)) -> np.ndarray:
    gray = np.full((canvas, canvas), 235, dtype=np.uint8)
    h, w = binary.shape
    y, x = offset
    region = gray[y:y + h, x:x + w]
    region[binary > 0] = 20
    return gray


def _ink_centroid(img: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(img < 128)
    return float(ys.mean()), float(xs.mean())


def test_shape_dtype_and_background():
    out = to_canonical(_to_gray(synthetic_glyph(random.Random(1))))
    assert is_canonical(out)
    assert out[0, 0] == 255 and out[-1, -1] == 255


def test_empty_returns_blank():
    out = to_canonical(np.full((90, 70), 245, dtype=np.uint8))
    assert is_canonical(out) and (out == 255).all()


def test_centroid_centered():
    out = to_canonical(_to_gray(synthetic_glyph(random.Random(2))))
    cy, cx = _ink_centroid(out)
    assert abs(cy - CANON_SIZE / 2) <= 1.5
    assert abs(cx - CANON_SIZE / 2) <= 1.5


def test_translation_invariance():
    glyph = synthetic_glyph(random.Random(3))
    a = to_canonical(_to_gray(glyph, canvas=160, offset=(8, 15)))
    b = to_canonical(_to_gray(glyph, canvas=160, offset=(70, 80)))
    both = ((a < 128) | (b < 128)).sum()
    diff = ((a < 128) != (b < 128)).sum()
    assert diff / max(both, 1) < 0.02


def test_no_upscale_preserves_native_pixels():
    """墨迹小于内容区时保持原生尺寸，不做放大重采样。"""
    glyph = synthetic_glyph(random.Random(4))          # 64×64 < 152 内容区
    out = to_canonical(_to_gray(glyph))
    ys, xs = np.nonzero(out < 128)
    gh = ys.max() - ys.min() + 1
    gw = xs.max() - xs.min() + 1
    src_ys, src_xs = np.nonzero(glyph)
    assert abs(gh - (src_ys.max() - src_ys.min() + 1)) <= 1
    assert abs(gw - (src_xs.max() - src_xs.min() + 1)) <= 1


def test_downscale_when_oversized():
    glyph = synthetic_glyph(random.Random(5))
    big = cv2.resize(glyph * 255, (300, 300), interpolation=cv2.INTER_NEAREST)
    gray = 255 - big  # 白底黑字
    out = to_canonical(np.pad(gray, 20, constant_values=255))
    ys, xs = np.nonzero(out < 128)
    content = round(CANON_SIZE * (1 - 2 * CANON_MARGIN_RATIO))
    assert max(ys.max() - ys.min(), xs.max() - xs.min()) <= content + 1


def test_clean_removes_edge_rule_line():
    """贴边贯穿竖线（界行残留）在 canonical 化时被清掉。"""
    glyph = synthetic_glyph(random.Random(6))
    gray = _to_gray(glyph, canvas=120, offset=(28, 30))
    gray[:, :4] = 30                       # 左贴边竖线
    out = to_canonical(gray)
    left_ink = (out[:, :30] < 128).sum()
    assert left_ink == 0


def test_idempotent():
    gray = _to_gray(synthetic_glyph(random.Random(7)))
    once = to_canonical(gray)
    twice = to_canonical(once)
    diff = ((once < 128) != (twice < 128)).sum()
    both = (once < 128).sum()
    assert diff / max(both, 1) < 0.02


def test_canonical_png_roundtrip():
    data = canonical_png(_to_gray(synthetic_glyph(random.Random(8))))
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert is_canonical(img)
