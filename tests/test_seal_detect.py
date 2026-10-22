"""印章定位（`steps/seal_detect.py`）：大印密度与版框正方形、小印模板覆盖、规范空间坐标。数据全在这里现造。"""

from __future__ import annotations

import numpy as np

from open_guji_cv.steps.seal_detect import (SealDetectParams, crisp_seals, detect_seals,
                                            stain_seals, _templates)

H, W = 3000, 2300


def _page() -> np.ndarray:
    return np.full((H, W), 255, np.uint8)


def _dots(img, x0, y0, x1, y1, n, seed=0):
    rng = np.random.default_rng(seed)
    for x, y in zip(rng.integers(x0, x1, n), rng.integers(y0, y1, n)):
        img[y:y + 4, x:x + 4] = 0     # 16 像素一点：中等墨点


def test_blank_page_has_no_seal():
    assert detect_seals(_page(), SealDetectParams()) == []


def test_square_dot_field_is_a_stain_seal_and_thin_strip_is_not():
    img = _page()
    _dots(img, 300, 300, 1800, 1800, 6000)
    found = stain_seals(img, min_peak=20)
    assert len(found) == 1
    (x0, y0, x1, y1), peak = found[0]
    assert x0 <= 300 and y0 <= 300 and x1 >= 1650 and y1 >= 1650 and peak >= 20

    strip = _page()
    _dots(strip, 1900, 300, 2150, 2700, 4000)     # 书签条：细长
    assert stain_seals(strip, min_peak=20) == []


def test_template_seal_found_even_with_text_inside():
    import cv2

    from open_guji_cv.steps.seal_detect import SEAL_TPL_DIR
    from open_guji_cv.utils.image_io import imread
    tpl = imread(str(sorted(SEAL_TPL_DIR.glob("*.png"))[0]), cv2.IMREAD_GRAYSCALE)
    img = _page()
    th, tw = tpl.shape
    img[400:400 + th, 900:900 + tw] = tpl
    img[600:900, 1100:1160] = 0                    # 印里压一道「字」
    assert _templates()
    hits = crisp_seals(img, min_cover=0.6, min_score=0.25)
    assert len(hits) == 1
    (x0, y0, _x1, _y1), score, _name = hits[0]
    assert abs(x0 - 900) <= 8 and abs(y0 - 400) <= 8 and score >= 0.25


def test_detect_reports_bbox_in_top_right_space():
    img = _page()
    _dots(img, 300, 300, 1800, 1800, 6000)
    (seal,) = detect_seals(img, SealDetectParams(min_cover=2.0))   # 关掉小印
    x0, _y0, x1, _y1 = seal.bbox
    # 左上原点 x∈[≤300, ≥1650] → 右上原点 x∈[W-1-x1, W-1-x0]
    assert seal.kind == "stain" and x1 >= W - 1 - 300 and x0 <= W - 1 - 1650


def test_stain_seal_is_the_square_at_the_frame_top_right():
    from types import SimpleNamespace as NS
    borders = NS(top=NS(y_at_right=330.0),
                 verticals=[NS(x_at_top=x, slope=0.0) for x in (340.0, 525.0, 2000.0)])
    img = _page()
    _dots(img, 300, 300, 1800, 1800, 6000)
    (seal,) = detect_seals(img, SealDetectParams(min_cover=2.0), borders)
    assert seal.source == "frame" and seal.bbox == (340.0, 330.0, 2000.0, 1990.0)
    # 没有大印的页，有版框也不出框
    assert detect_seals(_page(), SealDetectParams(), borders) == []
