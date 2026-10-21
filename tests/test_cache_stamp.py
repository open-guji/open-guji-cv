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


def test_stale_column_images_flags_shape_mismatch_only(tmp_path, monkeypatch):
    """缓存列图与现渲染形状不同 → 判过期；相同的不报。"""
    import numpy as np
    from types import SimpleNamespace
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.ops import cache_verify as cv
    cache = ImageCache(tmp_path)
    cache.put("b", "column_image", "p0001c01", np.zeros((100, 20), np.uint8))   # 与渲染同形
    cache.put("b", "column_image", "p0001c02", np.zeros((115, 20), np.uint8))   # 顶部多 15px
    renders = {"p0001c01": np.zeros((100, 20), np.uint8), "p0001c02": np.zeros((100, 20), np.uint8)}
    monkeypatch.setitem(STEPS, "column_warp", SimpleNamespace(render=lambda ctx, kind, key: renders[key]))
    eng = SimpleNamespace(cache=cache, book=SimpleNamespace(id="b"), ctx=None)
    assert cv.stale_column_images(eng, [1]) == {1: [2]}


def test_lazy_put_does_not_stamp_a_page_that_already_holds_unstamped_legacy_files(tmp_path):
    """戳是「这一页缓存可信」的凭据（verify 免查）：老缓存页补一张新图不能把整页老图一起洗白。"""
    c = ImageCache(tmp_path)
    c.put("b", "char_patch", "p0003c01s1", _img(10))                              # 老缓存：没戳
    c.put("b", "char_patch", "p0003c01s2", _img(20), stamp="X")                   # 惰性补一张
    assert c.page_stamp("b", "char_patch", "p0003c01s1") is None
    c.put("b", "char_patch", "p0004c01s1", _img(20), stamp="X")                   # 空页照常记戳
    c.put("b", "char_patch", "p0004c01s2", _img(20), stamp="X")
    assert c.page_stamp("b", "char_patch", "p0004c01s1") == "X"
    c.invalidate("b", "char_patch", key_prefix="p0003")                           # 清掉后重写：干净了，记戳
    c.put("b", "char_patch", "p0003c01s1", _img(10), stamp="X")
    assert c.page_stamp("b", "char_patch", "p0003c01s1") == "X"


def _verify_eng(tmp_path, stamps, manifest_sha):
    """verify_book 用的假引擎：p1 两列各 6 个字格；`stamps` 是缓存里记的戳，`manifest_sha` 是现行产物 sha。"""
    from types import SimpleNamespace as NS
    cache = ImageCache(tmp_path)
    chars = [NS(cell_type="char", patch_key=f"p0001c01s{s}") for s in range(1, 7)]
    for r in chars:
        cache.put("b", "char_patch", r.patch_key, _img(10))
    cache.put("b", "column_image", "p0001c01", _img(10))
    for kind, st in stamps.items():
        cache.set_page_stamp("b", kind, "p0001", st)
    reads = []
    store = NS(read=lambda *a: reads.append(a) or NS(columns=[NS(ok=True, col=1, chars=chars)]))
    ctx = NS(cache_stamp=lambda kind, key: manifest_sha)
    return NS(cache=cache, book=NS(id="b"), ctx=ctx, store=store), reads


def test_verify_book_trusts_pages_whose_stamps_match_and_full_checks_them_anyway(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.ops import cache_verify as cv
    rendered = []
    fake = NS(render=lambda ctx, kind, key: rendered.append(key) or _img(10))
    monkeypatch.setitem(STEPS, "cell_shrink", fake)
    monkeypatch.setitem(STEPS, "column_warp", fake)
    eng, reads = _verify_eng(tmp_path, {"char_patch": "S", "column_image": "S"}, "S")
    res = cv.verify_book(eng, [1], log=lambda *_: None)
    assert res["pages_trusted_by_stamp"] == {"char_patch": 1, "column_image": 1}
    assert reads == [] and rendered == [] and res["bad_columns"] == 0
    res = cv.verify_book(eng, [1], log=lambda *_: None, full=True)
    assert res["pages_trusted_by_stamp"] == {"char_patch": 0, "column_image": 0}
    assert reads and rendered and res["columns_checked"] == 1


def test_verify_book_still_checks_pages_with_a_stale_or_missing_stamp(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.ops import cache_verify as cv
    fake = NS(render=lambda ctx, kind, key: _img(10))
    monkeypatch.setitem(STEPS, "cell_shrink", fake)
    monkeypatch.setitem(STEPS, "column_warp", fake)
    eng, reads = _verify_eng(tmp_path, {"char_patch": "OLD"}, "NEW")            # 字块戳过期、列图没戳
    res = cv.verify_book(eng, [1], log=lambda *_: None)
    assert res["pages_trusted_by_stamp"] == {"char_patch": 0, "column_image": 0}
    assert reads and res["columns_checked"] == 1


def test_cache_warm_does_not_stamp_pages_that_held_unstamped_legacy_files(tmp_path):
    from types import SimpleNamespace as NS
    from open_guji_cv.ops.cache_warm import _stamp_pass
    cache = ImageCache(tmp_path)
    cache.put("b", "char_patch", "p0001c01s1", _img(10))                          # 老缓存页
    ctx = NS(cache=cache, book=NS(id="b"), producer=lambda kind: None,
             cache_stamp=lambda kind, key: "CUR")
    legacy = _stamp_pass(ctx, [1, 2], drop=True)
    assert legacy == {("char_patch", "p0001")}
    cache.put("b", "char_patch", "p0002c01s1", _img(10))                          # 预渲出来的（worker 不写戳）
    _stamp_pass(ctx, [1, 2], drop=False, skip=legacy)
    assert cache.page_stamp("b", "char_patch", "p0001c01s1") is None
    assert cache.page_stamp("b", "char_patch", "p0002c01s1") == "CUR"
