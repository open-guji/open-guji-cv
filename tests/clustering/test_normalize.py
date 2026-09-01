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


# ── P3 重写 remove_edge_specks 的定向单测（2026-08-23）──────────────

def _canvas(h=140, w=150):
    return np.full((h, w), 235, dtype=np.uint8)


def test_parallel_stroke_at_edge_is_kept():
    """「二」的底横贴到图块底边也不能删——旧 shallow_tb 的实锤误杀
    （vol02:157:2:4）。笔画厚（10px），够不着细线档。"""
    g = _canvas()
    g[55:65, 30:120] = 25                      # 上横
    g[130:140, 30:120] = 25                    # 底横：贴底边
    out = normalize_patch(g, stroke_width=None)
    n, _, stats, _ = __import__('cv2').connectedComponentsWithStats(out, 8)
    assert n - 1 == 2, f"底横被删了（组件数 {n-1}）"


def test_thin_line_removed_anywhere():
    """版框/界行细线（3px）不论贴不贴边都删——golden 集 031/034/036 根因。"""
    import cv2
    g = _canvas()
    g[40:105, 40:105] = 235
    cv2.rectangle(g, (45, 45), (105, 105), 25, 8)   # 主体：厚笔画方框
    g[118:121, 10:145] = 25                    # 中下部一条细横线，不贴边
    out = normalize_patch(g, stroke_width=None)
    ys, xs = np.nonzero(out)
    # 细线若保留，归一图高度会被它撑满；删除后墨迹接近方形
    hh = ys.max() - ys.min() + 1
    ww = xs.max() - xs.min() + 1
    assert abs(hh - ww) <= hh * 0.25, f"细线残留（h={hh} w={ww}）"


def test_crossing_vline_removed():
    """贯穿字身的界行竖线（不贴左右边）也要删——golden 036。"""
    import cv2
    g = _canvas()
    cv2.rectangle(g, (45, 45), (110, 110), 25, 9)
    g[3:137, 70:73] = 25                       # 3px 竖线纵贯，居中
    # 竖线与方框相交会连通——把线挪到不相交的位置
    g2 = _canvas()
    cv2.rectangle(g2, (30, 45), (90, 110), 25, 9)
    g2[3:137, 120:123] = 25                    # 纵贯竖线，在主体右侧
    out = normalize_patch(g2, stroke_width=None)
    ys, xs = np.nonzero(out)
    ww = xs.max() - xs.min() + 1
    hh = ys.max() - ys.min() + 1
    assert ww <= hh * 1.3, f"竖线残留把宽度撑开（h={hh} w={ww}）"


def test_lone_hbar_char_survives():
    """「一」自己就是主体（最大组件），细线档的护栏必须保它。"""
    g = _canvas()
    g[65:74, 25:130] = 25
    out = normalize_patch(g, stroke_width=None)
    assert out.sum() > 100


def test_padding_band_debris_removed_but_core_dot_kept():
    """padding 带小残片删；核心区里的游离点画（之/亦的点）保留。"""
    g = _canvas()
    g[50:105, 45:105] = 25                     # 主体大块
    g[3:9, 60:80] = 25                         # 顶部 padding 带里的邻字残片
    g[28:36, 70:78] = 25                       # 核心区上部的游离点（之/文 的点）
    out = normalize_patch(g, stroke_width=None)
    n, _, stats, _ = __import__('cv2').connectedComponentsWithStats(out, 8)
    assert n - 1 == 2, f"应保留主体+点共 2 个组件，实得 {n-1}"


def test_thin_line_position_guard():
    """细线判据带位置守卫：字身中部的细长横是笔画，不是版框。

    实锤 vol01:26:3:5「壽」——中部一条磨损印细（3~4px）、又断开、又跨
    半宽的真横，被位置无关的细线判据当界行删掉（用户在库页面上看出
    「短笔画被消掉」）。守卫后：外带的竖界行照删，中部细横必须留。
    """
    import numpy as np
    from open_guji_cv.clustering.normalize import remove_edge_specks

    h = w = 120
    img = np.zeros((h, w), dtype=np.uint8)
    # 主体：一个厚笔画的方框（最大组件）
    img[20:100, 30:38] = 1
    img[20:28, 30:90] = 1
    # 中部细长横（厚 3px、跨 70px > 0.5w）——真笔画，必须保留
    img[58:61, 25:95] = 1
    # 贴右边的细竖线（界行）——照删
    img[5:115, 114:117] = 1
    out = remove_edge_specks(img)
    assert out[59, 60] == 1, "字身中部的细横被误删"
    assert out[60, 115] == 0, "外带的竖界行没删掉"
