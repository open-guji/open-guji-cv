# -*- coding: utf-8 -*-
"""搬家登记（core/code_equiv.MOVED）的守卫：切分代码搬进 books/<套书>/ 后，产物指纹不变。"""
import importlib
import importlib.util

import open_guji_cv.steps  # noqa: F401  注册全部 Step
from open_guji_cv.core import code_equiv
from open_guji_cv.core.engine import _fingerprint_name, _module_source_hash
from open_guji_cv.core.step import STEPS


def test_moved_modules_are_gone_from_old_place_and_live_in_books():
    for new, (old, h) in code_equiv.MOVED.items():
        assert new.startswith("open_guji_cv.books."), new
        assert importlib.util.find_spec(new) is not None, f"{new} 不存在"
        assert importlib.util.find_spec(old) is None, f"{old} 搬走后旧位置还留着文件"
        assert len(h) == 64


def test_moved_modules_are_in_some_step_fingerprint():
    mods = {m for st in STEPS.values() for m in (type(st).__module__, *st.spec.code_deps)}
    for new in code_equiv.MOVED:
        assert new in mods, f"{new} 不在任何 Step 的指纹里，登记它没用"


def test_fingerprint_name_follows_moved_code():
    """代码仍是搬家时那一版 → 指纹里用旧名；之后改过 → 用新名（产物照常过期）。"""
    for new, (old, h) in code_equiv.MOVED.items():
        want = old if _module_source_hash(new) == h else new
        assert _fingerprint_name(new) == want
