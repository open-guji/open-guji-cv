# -*- coding: utf-8 -*-
"""套书分叉复制（core/code_equiv.FORKED）的守卫：全唐文 books/quantangwen 从殿本复制 Step3 行切分（2026-11-04）。"""
import importlib.util
import inspect

import open_guji_cv.steps  # noqa: F401  注册全部 Step
from open_guji_cv.core import code_equiv, seg_set
from open_guji_cv.core.engine import _fingerprint_name, _module_source_hash, code_hash
from open_guji_cv.core.step import STEPS


class _Book:
    pipeline = "keben_body_v2"

    def __init__(self, ss):
        self.seg_set = ss


def test_forked_copies_exist_next_to_original_and_are_overrides():
    pairs = {(d, m) for ov in seg_set.OVERRIDES.values() for d, m in ov.items()}
    for new, (old, h) in code_equiv.FORKED.items():
        assert new.startswith("open_guji_cv.books."), new
        assert importlib.util.find_spec(new) is not None, f"{new} 不存在"
        assert importlib.util.find_spec(old) is not None, f"{old} 是分叉的原模块，应当还在"
        assert (old, new) in pairs, f"{new} 没在 seg_set.OVERRIDES 里登记覆盖 {old}"
        assert len(h) == 64


def test_forked_copy_fingerprints_under_original_name_while_unchanged():
    for new, (old, h) in code_equiv.FORKED.items():
        if _module_source_hash(new) == h:
            assert _fingerprint_name(new) == _fingerprint_name(old)
        else:
            assert _fingerprint_name(new) == new


def test_quantangwen_steps_fingerprint_like_siku_while_copies_unchanged():
    """复制没改过时，全唐文册各步指纹与殿本缺省相同（分叉本身不让全唐文产物过期）。"""
    if any(_module_source_hash(n) != h for n, (o, h) in code_equiv.FORKED.items() if ".quantangwen." in n):
        return
    for sid, st in STEPS.items():
        assert code_hash(st, book=_Book("quantangwen")) == code_hash(st, book=_Book(None)), sid


def test_single_head_only_in_quantangwen():
    from open_guji_cv.books.quantangwen import row_boundaries as qtw
    from open_guji_cv.books.siku_zongmu import row_boundaries as siku
    assert "jiazhu_single_head" in inspect.signature(qtw.segment_column).parameters
    assert "jiazhu_single_head" not in inspect.signature(siku.segment_column).parameters
    assert seg_set.resolve(_Book("quantangwen"), "open_guji_cv.books.siku_zongmu.row_boundaries") == qtw.__name__
    assert seg_set.resolve(_Book(None), "open_guji_cv.books.siku_zongmu.row_boundaries") == siku.__name__
