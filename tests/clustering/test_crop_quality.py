"""crop_quality 单测：三档分级 + 两条判据各自的正反例。"""

import numpy as np

from open_guji_cv.clustering.crop_quality import assess_crop


def _patch(h=130, w=130, bg=240):
    return np.full((h, w), bg, dtype=np.uint8)


def _core_char(g, margin=12):
    """核心区里画一个「口」形（四条边，多连通体测试另建）。"""
    h, w = g.shape
    g[margin + 20:h - margin - 20, margin + 20:margin + 26] = 20
    g[margin + 20:h - margin - 20, w - margin - 26:w - margin - 20] = 20
    g[margin + 20:margin + 26, margin + 20:w - margin - 20] = 20
    g[h - margin - 26:h - margin - 20, margin + 20:w - margin - 20] = 20
    return g


def test_clean_char():
    q = assess_crop(_core_char(_patch()), margins=(12, 12))
    assert q.tier == "clean" and not q.truncated and not q.residue


def test_multi_component_char_is_still_clean():
    """汉字部件互不相连（門/百/卷…）：核心区里的非主体连通体不算残留。"""
    g = _core_char(_patch())
    g[55:75, 55:75] = 20                       # 核心区中央一块独立部件
    q = assess_crop(g, margins=(12, 12))
    assert q.tier == "clean" and q.n_foreign == 0


def test_neighbor_in_padding_band_is_normal():
    """邻字探进 padding 带（碰边但不进核心区）是常态，不算残留。"""
    g = _core_char(_patch())
    g[0:8, 40:90] = 20                         # 顶部 padding 带里一条邻字横笔
    q = assess_crop(g, margins=(12, 12))
    assert q.tier == "clean"


def test_intrusion_reaching_core_is_residue():
    g = _core_char(_patch())
    g[0:30, 60:70] = 20                        # 从上边界一直伸进核心区
    q = assess_crop(g, margins=(12, 12))
    assert q.tier == "degraded" and q.residue and not q.truncated


def test_main_component_cut_at_border_is_truncated():
    g = _core_char(_patch())
    g[0:26, 55:75] = 20                        # 主体的粗竖笔一直顶到上边界（20px 宽）
    g[26:34, 50:80] = 20                       # 与「口」连上，成为主体一部分
    q = assess_crop(g, margins=(12, 12))
    assert q.truncated and q.tier == "degraded"


def test_empty_patch():
    assert assess_crop(_patch()).tier == "empty"


def test_binary_source_image():
    """灰度源本来就是二值图（s6）：Otsu 阈值为 0，墨不能被判空。"""
    g = _core_char(_patch(bg=255))
    g[g == 20] = 0
    q = assess_crop(g, margins=(12, 12))
    assert q.tier == "clean" and q.main_area > 0
