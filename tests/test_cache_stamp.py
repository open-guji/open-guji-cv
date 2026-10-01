# -*- coding: utf-8 -*-
"""图像缓存页级戳 + `guji cache verify` 的错位判据（2026-10-01，vol03 缓存与换进来的产物不一代事故）。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.ops.cache_verify import best_offset
from open_guji_cv.products.cache import ImageCache


def _img(v):
    return np.full((20, 20), v, np.uint8)


def test_stamp_mismatch_drops_the_page_but_not_other_pages(tmp_path):
    c = ImageCache(tmp_path)
    c.put("b", "char_patch", "p0009c01s1", _img(10), stamp="A")
    c.put("b", "char_patch", "p0009c01s2", _img(20), stamp="A")
    c.put("b", "char_patch", "p0010c01s1", _img(30), stamp="B")
    assert c.get("b", "char_patch", "p0009c01s1", stamp="A") is not None          # 戳对得上
    assert c.get("b", "char_patch", "p0009c01s1", stamp="A2") is None             # 产物换了 → 过期
    assert c.get("b", "char_patch", "p0009c01s2") is None                         # 整页该种类都清了
    assert c.get("b", "char_patch", "p0010c01s1", stamp="B") is not None          # 别的页不动


def test_unstamped_legacy_cache_is_still_served_and_materialize_stamps_new_files(tmp_path):
    c = ImageCache(tmp_path)
    c.put("b", "char_patch", "p0001c01s1", _img(10))                              # 老缓存：没戳
    assert c.get("b", "char_patch", "p0001c01s1", stamp="X") is not None          # 无从验证 → 放行
    calls = []
    p = c.materialize("b", "char_patch", "p0002c01s1", lambda: calls.append(1) or _img(5), stamp="X")
    assert p.exists() and calls == [1] and c.page_stamp("b", "char_patch", "p0002c01s1") == "X"
    # 同戳再取不再重算；换戳重算
    c.materialize("b", "char_patch", "p0002c01s1", lambda: calls.append(2) or _img(5), stamp="X")
    c.materialize("b", "char_patch", "p0002c01s1", lambda: calls.append(3) or _img(6), stamp="Y")
    assert calls == [1, 3]


def test_invalidate_whole_kind_also_forgets_stamps_and_prune_tolerates_stamp_file(tmp_path):
    c = ImageCache(tmp_path)
    c.put("b", "column_image", "p0001c01", _img(1), stamp="A")
    assert c.invalidate("b", "column_image") == 1
    assert c.page_stamp("b", "column_image", "p0001c01") is None
    c.put("b", "column_image", "p0002c01", _img(1), stamp="A")
    c.prune(0)                                                                    # 戳文件被 LRU 掉不炸
    assert c.get("b", "column_image", "p0002c01", stamp="A") is None


def test_best_offset_flags_a_one_cell_shift_only_when_neighbour_is_clearly_closer():
    def glyph(seed):
        r = np.random.RandomState(seed)
        return (r.rand(64, 64) * 255).astype(np.uint8)
    a, b, c = glyph(1), glyph(2), glyph(3)
    assert best_offset(b, b, a, c) == 0                  # 缓存就是本格
    assert best_offset(a, b, a, c) == -1                 # 缓存其实是上一格的图
    assert best_offset(c, b, a, c) == 1
    assert best_offset(b, b, None, None) == 0            # 列首尾没有邻格不误报
