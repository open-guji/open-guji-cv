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


def test_narrow_dot_field_is_not_the_frame_wide_stain():
    """卷末淡印（vol35 p173）：窄密度区不按大印套整个版框宽的正方形；模板又不像，就不算印。"""
    from types import SimpleNamespace as NS
    borders = NS(top=NS(y_at_right=330.0),
                 verticals=[NS(x_at_top=x, slope=0.0) for x in (340.0, 525.0, 2000.0)])
    img = _page()
    _dots(img, 900, 400, 1500, 1000, 1000)
    assert stain_seals(img, min_peak=20)
    assert detect_seals(img, SealDetectParams(min_cover=2.0), borders) == []


def _seal_ctx(cells, seals, gray=None):
    from types import SimpleNamespace as NS
    prods = {"cells": cells, "seals": seals}
    return NS(product=lambda kind, page: prods[kind], has_product=lambda kind, page: kind in prods,
              raw_page=lambda page: gray)


def _cells(*cols):
    """cols：[(col, [(slot, 规范空间 x0, y0, x1, y1)])]"""
    from types import SimpleNamespace as NS
    return NS(columns=[NS(col=c, cells=[NS(slot=s, sub=None, quad_page=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
                                       for s, x0, y0, x1, y1 in cs]) for c, cs in cols])


def test_page_occluded_is_the_cells_under_the_big_seal():
    from types import SimpleNamespace as NS
    from open_guji_cv.products.kinds.seals import PageSeals, Seal
    from open_guji_cv.steps.occlusion import page_occluded
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    cells = _cells((1, [(1, 300, 300, 480, 400), (2, 300, 400, 480, 500), (9, 300, 1500, 480, 1600),
                        (10, 300, 1600, 480, 1700)]))
    seals = PageSeals(page=3, width=W, height=H, seals=[
        Seal(kind="stain", bbox=(300, 330, 2000, 1490), score=33.0, source="frame"),
        Seal(kind="crisp", bbox=(300, 1500, 960, 2180), score=0.6, source="template", template="x.png")])
    gray = _page()
    gray[1520:1580, W - 1 - 460:W - 1 - 320] = 0               # 9 格（规范空间 x 300..480）里有字；10 格只有印（这里没墨）
    occ = page_occluded(_seal_ctx(cells, seals, gray), 3, SeedAdmitParams())
    # 1 格与大印重叠 0.7、2 格 1.0；9 格是小印压着的字；10 格没有印外的墨，是盖章空栏，不算遮挡
    assert occ == {(1, 1, ""): 33.0, (1, 2, ""): 33.0, (1, 9, ""): 0.6}


def test_page_seal_blank_uses_the_small_seal_and_page_coordinates():
    from open_guji_cv.products.kinds.seals import PageSeals, Seal
    from open_guji_cv.steps.occlusion import page_seal_blank
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    gray = _page()
    # 规范空间 x 1400..1580 ↔ 原图 x 719..899；格 2 里有一块不在印笔画上的墨（模板名读不到 → 没有笔画覆盖区）
    gray[520:580, 760:820] = 0
    cells = _cells((7, [(1, 1400, 340, 1580, 460), (2, 1400, 460, 1580, 600), (3, 1400, 1200, 1580, 1300)]))
    seals = PageSeals(page=9, width=W, height=H, seals=[
        Seal(kind="crisp", bbox=(830, 340, 1490, 1020), score=0.6, source="template", template="缺.png")])
    p = SeedAdmitParams(seal_blank_page=True, lane_seal=True)
    got = page_seal_blank(_seal_ctx(cells, seals, gray), 9, p)
    assert set(got) == {(7, 1, "")}                            # 2 格印外有墨退出；3 格不在印框里
    assert got[(7, 1, "")]["overlap"] == 0.5
