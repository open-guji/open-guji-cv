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


def _now(mod: str) -> str:
    """原模块之后又搬过家（如 2026-11-09 books/siku_zongmu → impl/keben）：沿 MOVED 反查现在的名字。"""
    back = {o: n for n, (o, _) in code_equiv.MOVED.items()}
    seen = set()
    while mod in back and mod not in seen:
        seen.add(mod)
        mod = back[mod]
    return mod


def test_forked_copies_exist_next_to_original_and_are_overrides():
    pairs = {(d, m) for ov in seg_set.OVERRIDES.values() for d, m in ov.items()}
    for new, (old, h) in code_equiv.FORKED.items():
        assert new.startswith("open_guji_cv.books."), new
        assert importlib.util.find_spec(new) is not None, f"{new} 不存在"
        old = _now(old)
        assert importlib.util.find_spec(old) is not None, f"{old} 是分叉的原模块，应当还在"
        assert (old, new) in pairs, f"{new} 没在 seg_set.OVERRIDES 里登记覆盖 {old}"
        assert len(h) == 64


def test_forked_copy_fingerprints_under_original_name_while_unchanged():
    for new, (old, h) in code_equiv.FORKED.items():
        if _module_source_hash(new) == h:
            assert _fingerprint_name(new) == _fingerprint_name(_now(old))
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
    from open_guji_cv.impl.keben import row_boundaries as siku
    assert "jiazhu_single_head" in inspect.signature(qtw.segment_column).parameters
    assert "jiazhu_single_head" not in inspect.signature(siku.segment_column).parameters
    assert seg_set.resolve(_Book("quantangwen"), "open_guji_cv.impl.keben.row_boundaries") == qtw.__name__
    assert seg_set.resolve(_Book(None), "open_guji_cv.impl.keben.row_boundaries") == siku.__name__


def test_editing_quantangwen_copy_expires_only_quantangwen(monkeypatch):
    """全唐文改自己那份 row_boundaries：全唐文册 row_segment 指纹变（产物判过期），殿本、史記册不变。"""
    from open_guji_cv.core import engine
    st = STEPS["row_segment"]
    before = {ss: code_hash(st, book=_Book(ss)) for ss in (None, "shiji_wyg", "quantangwen")}
    mod = "open_guji_cv.books.quantangwen.row_boundaries"
    monkeypatch.setitem(engine._code_hash_cache, mod, "0" * 64)
    after = {ss: code_hash(st, book=_Book(ss)) for ss in (None, "shiji_wyg", "quantangwen")}
    assert after["quantangwen"] != before["quantangwen"]
    assert after[None] == before[None] and after["shiji_wyg"] == before["shiji_wyg"]
