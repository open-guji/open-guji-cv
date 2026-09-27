# -*- coding: utf-8 -*-
"""`core/anchor.py`：页面坐标空间换算 + `crop_patch()`（任务卡 #54 第12条）。

`bbox_page`（`raw_page_px@top-right`）原点在页面右上角、x 从右往左量；
`cv2`/`numpy` 图是左上原点。直接拿 `bbox_page` 当左上原点 bbox 去裁会静默裁到
另一个字——`console/routers/products.py` 那次实审就是这么栽的（p3c11s11「鳳」，
详见该文件模块头注释）。`crop_patch()` 把换算与切片包在一起，这里钉死它别再
让人自己写镜像公式。
"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.core.anchor import bbox_tl_to_tr, bbox_tr_to_tl, crop_patch, to_cv
from open_guji_cv.core.spec import RAW_TL, RAW_TR


def test_bbox_tl_to_tr_is_involution():
    """左上→右上→左上要回到原值——用户 09-03 定的换算是自对合的。"""
    bbox = (100.0, 20.0, 140.0, 60.0)
    W = 300
    tr = bbox_tl_to_tr(bbox, W)
    back = bbox_tr_to_tl(tr, W)
    assert back == pytest.approx(bbox)


def test_to_cv_raw_tl_passthrough():
    assert to_cv((10, 20, 30, 40), 300, space=RAW_TL) == (10, 20, 30, 40)


def test_to_cv_raw_tr_mirrors_x():
    """右上原点 x=1467（此前那次实审报的真实坏例数字）在宽 W=3024 的页上，
    应该换算到左上原点 x≈1243 附近——不是原样照抄。"""
    # 复刻 products.py 模块头记的那次实审：W-1-1557=1466（bx1 处），
    # 真身左上 x0≈1243。这里造一个形状匹配、边界对得上的最小可复现例。
    W = 3024
    bx0, bx1 = 1467.0, 1467.0 + 60.0    # 右上原点下的窄框
    x0, y0, x1, y1 = to_cv((bx0, 0.0, bx1, 10.0), W, space=RAW_TR)
    # 右上原点 x 越大离左边越远；镜像后左上原点 x 应该显著小于 W-bx0，
    # 且不等于 bx0/bx1 本身（"直接照抄"就会踩这个坑）。
    assert x0 != int(bx0) and x1 != int(bx1)
    assert x0 == (W - 1) - int(round(bx1))
    assert x1 == (W - 1) - int(round(bx0))


def test_crop_patch_matches_manual_to_cv_slice():
    img = np.arange(40 * 30, dtype=np.uint8).reshape(30, 40)
    bbox = (5.0, 3.0, 15.0, 10.0)   # raw_page_px@top-right
    patch = crop_patch(img, bbox)
    x0, y0, x1, y1 = to_cv(bbox, img.shape[1])
    assert np.array_equal(patch, img[y0:y1, x0:x1])
    assert patch.shape[0] > 0 and patch.shape[1] > 0


def test_crop_patch_would_grab_wrong_region_if_naively_sliced():
    """直接拿 bbox_page 当左上原点去裁 vs 用 `crop_patch()`——两者必须给出
    不同的图块（除非框恰好落在页面正中，这里故意选一个偏一侧的框）。
    这条断言就是"静默裁到另一个字"那类坏形态的护栏：谁把 `crop_patch`
    悄悄改回"直接切片、不做镜像"，这里立刻不通过。"""
    img = np.zeros((50, 200), dtype=np.uint8)
    img[:, 170:190] = 255   # 真身在图的右侧（左上原点意义下）
    bbox_page = (10.0, 0.0, 30.0, 50.0)   # 右上原点：离右边 10~30px，对应左上原点右侧
    naive = img[0:50, 10:30]             # 如果不做镜像，会切到左侧（全 0）
    correct = crop_patch(img, bbox_page)
    assert naive.sum() == 0
    assert correct.sum() > 0, "crop_patch 应该裁到真身（右侧的亮块），不是照抄左上原点的裸切片"


def test_crop_patch_returns_none_when_degenerate_or_out_of_bounds():
    img = np.zeros((50, 60), dtype=np.uint8)
    assert crop_patch(img, (1000.0, 1000.0, 1001.0, 1001.0)) is None   # 全在图外
    assert crop_patch(img, (5.0, 5.0, 5.0, 5.0)) is None               # 宽/高为 0
