# -*- coding: utf-8 -*-
"""控制台禁止现建大模板索引（utils/inline_index.py，overview#237）。"""
import pytest

from open_guji_cv.errors import IndexNotBuilt
from open_guji_cv.console.errors import status_of
from open_guji_cv.utils.inline_index import INLINE_LIMIT, forbid_inline_build


def test_no_env_never_raises(monkeypatch):
    monkeypatch.delenv("GUJI_FORBID_INLINE_INDEX", raising=False)
    forbid_inline_build("字体 HOG", INLINE_LIMIT * 10, "x.npz")


def test_env_small_table_allowed(monkeypatch):
    monkeypatch.setenv("GUJI_FORBID_INLINE_INDEX", "1")
    forbid_inline_build("CNN embedding", 4, "x.npz")          # 组内 closed-set 之类照常现建


def test_env_big_table_raises_503(monkeypatch):
    monkeypatch.setenv("GUJI_FORBID_INLINE_INDEX", "1")
    with pytest.raises(IndexNotBuilt) as ei:
        forbid_inline_build("CNN embedding", INLINE_LIMIT + 1, "emb_x.npz")
    assert status_of(ei.value) == 503
    assert "build-rare-index" in str(ei.value)


def test_font_index_guard_hits_before_rendering(monkeypatch, tmp_path):
    from open_guji_cv.clustering import font_candidates as fc
    monkeypatch.setenv("GUJI_FORBID_INLINE_INDEX", "1")
    monkeypatch.setattr(fc, "_index_dir", lambda: tmp_path)   # 空目录：必然缺盘
    fc._index.cache_clear() if hasattr(fc._index, "cache_clear") else None
    big = tuple(chr(0x4E00 + i) for i in range(INLINE_LIMIT + 5))
    with pytest.raises(IndexNotBuilt):
        fc._index(big)
