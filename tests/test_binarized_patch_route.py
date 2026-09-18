"""`?src=bin` 从整页二值副本重裁字块：**坐标系必须翻对**。

`bbox_page` 是右上原点规范空间（x 向左递增），磁盘上的图是左上原点。不翻 x 的
后果是**静默裁到另一个字**——y 一点不差、尺寸也对，看着像「图没对齐」，
不像「坐标系错了」。2026-09-16 实测 p3 c11 s11「鳳」：bbox_page x=1467，
真实位置 x=1243，正好差 (W-1)-1557。
"""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from open_guji_cv.utils.binarized import binarize_page


#: 本文件一律 `edge_margin=0`：`binarize_page` 默认会把纸缘 20px 强制判纸
#: （挡扫描纸边的浅灰渐变，见该函数 docstring），而这里的合成记号有意贴在
#: 图像边上。这几个用例验的是**规范空间 ↔ 图像坐标的 x 翻转**，跟纸缘护栏
#: 是两回事，不该被它影响。
_BIN = dict(edge_margin=0)


def _page_with_marks(w=400, h=200):
    """左右各放一个可区分的记号：左边一根竖条，右边一个方框。"""
    g = np.full((h, w), 205, np.uint8)
    g[60:140, 40:52] = 25                      # 左侧竖条
    g[60:140, 330:392] = 205
    g[60:68, 330:392] = 25                     # 右侧方框（四边）
    g[132:140, 330:392] = 25
    g[60:140, 330:338] = 25
    g[60:140, 384:392] = 25
    return g


def test_mirror_maps_canonical_x_back_to_image_x():
    """规范空间 x → 图像 x 的换算：`x_img = (W-1) - x_canon`，左右边界互换。"""
    w = 400
    # 右侧方框在图像坐标 330..392；它在规范空间里的 x 是 (w-1)-392 .. (w-1)-330
    canon_x0, canon_x1 = (w - 1) - 392, (w - 1) - 330
    img_x0 = (w - 1) - canon_x1
    img_x1 = (w - 1) - canon_x0
    assert (img_x0, img_x1) == (330, 392)


def test_crop_by_mirrored_bbox_lands_on_the_right_mark():
    """按镜像后的坐标裁，拿到的必须是**右侧方框**那块，不是左侧竖条。"""
    g = _page_with_marks()
    b = binarize_page(g, **_BIN)
    w = g.shape[1]
    canon_x0, canon_x1 = (w - 1) - 392, (w - 1) - 330      # 规范空间里的右侧方框
    x0, x1 = (w - 1) - canon_x1, (w - 1) - canon_x0
    crop = b[60:140, x0:x1]
    # 方框是空心的：中间一行两端有墨、正中没有
    mid = crop[crop.shape[0] // 2]
    assert mid[0] == 0 and mid[-1] == 0, "方框左右边应当有墨"
    assert mid[len(mid) // 2] == 255, "方框中间应当是空的（说明裁的是方框不是竖条）"


def test_not_mirroring_would_grab_the_wrong_mark():
    """反面证据：**不翻** x 直接拿规范坐标去裁，会裁到左侧那根实心竖条上。"""
    g = _page_with_marks()
    b = binarize_page(g, **_BIN)
    w = g.shape[1]
    canon_x0, canon_x1 = (w - 1) - 392, (w - 1) - 330
    wrong = b[60:140, canon_x0:canon_x1]                   # 忘了翻
    mid = wrong[wrong.shape[0] // 2]
    assert (mid == 0).any(), "这一刀会切到左侧竖条——正是要防的静默错位"
