# -*- coding: utf-8 -*-
"""代码等价登记（`core/code_equiv.py`）的守卫。"""

from __future__ import annotations

import open_guji_cv.steps  # noqa: F401  —— 注册全部 Step
from open_guji_cv.core import code_equiv
from open_guji_cv.core.code_equiv import Equiv, canonical
from open_guji_cv.core.engine import _module_source_hash
from open_guji_cv.core.step import STEPS


def test_registry_is_not_a_code_dep():
    """登记表进了谁的 code_deps，改登记就让那一步整体过期——正是它要躲开的。"""
    for sid, st in STEPS.items():
        assert "open_guji_cv.core.code_equiv" not in {type(st).__module__, *st.spec.code_deps}, sid


def test_entries_are_well_formed():
    mods = {m for st in STEPS.values() for m in (type(st).__module__, *st.spec.code_deps)}
    mods |= set(code_equiv.SPLITS)   # 拆没了的旧模块：登记留着当历史（只增不删），指纹靠 SPLITS 里的旧哈希
    seen = set()
    for e in code_equiv.ENTRIES:
        assert e.module in mods, f"{e.module} 不在任何 Step 的指纹里，登记它没用"
        assert len(e.new) == 64 and len(e.old) == 64 and e.new != e.old
        assert e.evidence.strip(), "每条登记都要写证据"
        assert (e.module, e.new) not in seen, "同一个新哈希登记了两次"
        seen.add((e.module, e.new))


def test_current_code_maps_to_registered_old_hash():
    """登记过的模块：现在的代码要么正是登记的新代码（指纹换回旧哈希），要么之后又真改了
    （不在表里，照常判过期）。这里只核前一种确实生效。"""
    for e in code_equiv.ENTRIES:
        if canonical(e.module, e.new) == _module_source_hash(e.module):
            return
    assert not code_equiv.ENTRIES, "登记表里没有一条对得上现在的代码"


def test_canonical_follows_chain_and_survives_cycles(monkeypatch):
    a, b, c = "a" * 64, "b" * 64, "c" * 64
    monkeypatch.setattr(code_equiv, "_TABLE", {"m": {a: b, b: c}})
    assert canonical("m", a) == c
    assert canonical("m", "x" * 64) == "x" * 64
    assert canonical("other", a) == a
    monkeypatch.setattr(code_equiv, "_TABLE", {"m": {a: b, b: a}})
    assert canonical("m", a) in (a, b)          # 登记成环也不死循环
    assert isinstance(Equiv("m", a, b, "x"), Equiv)
