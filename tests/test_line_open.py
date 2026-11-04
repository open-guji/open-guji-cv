"""`clustering.page_type.line_open`：长线形核开运算的计数写法，与 cv2 原式逐位相同。

页型判定（border_detect_gate 每页都跑）原来用 `cv2.dilate(cv2.erode(b, K), K)`，单线程时长核每像素 O(k)；
换成 `boxFilter` 计数（2026-11-03）。这里拿原式在随机图上逐位比：奇偶 k、k=1、k 超过边长、整行整列全墨。
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.page_type import line_open, page_features


def _ref(b: np.ndarray, k: int, axis: int) -> np.ndarray:
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k) if axis == 0 else (k, 1))
    return cv2.dilate(cv2.erode(b, kern), kern)


@pytest.mark.parametrize("axis", [0, 1])
def test_line_open_matches_cv2(axis):
    rng = np.random.default_rng(7)
    for trial in range(150):
        h, w = (int(x) for x in rng.integers(1, 80, 2))
        b = (rng.random((h, w)) < rng.random()).astype(np.uint8)
        if trial % 3 == 0:
            b[:, int(rng.integers(0, w))] = 1
            b[int(rng.integers(0, h)), :] = 1
        n = b.shape[axis]
        for k in {1, 2, 3, 4, 5, int(rng.integers(1, 120)), n, n + 1, 2 * n + 3}:
            got = line_open(b, k, axis)
            assert got.dtype == np.uint8 and got.shape == b.shape
            assert np.array_equal(got, _ref(b, k, axis)), (trial, h, w, k)


def test_page_features_on_lined_page():
    """有界行、有字块的合成页：特征照常（竖线计数靠 line_open）。"""
    g = np.full((600, 400), 230, np.uint8)
    for x in range(40, 380, 40):
        g[30:570, x:x + 3] = 10
    rng = np.random.default_rng(0)
    for _ in range(120):
        y, x = int(rng.integers(40, 540)), int(rng.integers(45, 360))
        g[y:y + 12, x:x + 10] = 20
    f = page_features(g)
    assert f["n_vline"] == 9 and f["n_glyph"] > 40
