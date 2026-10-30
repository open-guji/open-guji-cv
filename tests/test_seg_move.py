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
        assert new.startswith(("open_guji_cv.books.", "open_guji_cv.seg.")), new
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


def test_split_collapses_back_to_old_module_while_parts_unchanged(monkeypatch):
    """拆分登记：几块都在、都没改 → 合回旧名＋旧哈希（与拆分前的公式逐位相同）；有一块改过 → 不合并。"""
    import hashlib

    from open_guji_cv.core import engine

    a, b = "open_guji_cv.seg.seam", "open_guji_cv.seg.cut_select"
    ha, hb = _module_source_hash(a), _module_source_hash(b)
    old, old_h = "open_guji_cv.utils.old_mod", "f" * 64
    mods = ["open_guji_cv.steps.cell_shrink", a, "open_guji_cv.steps.occlusion", b]

    def digest(pairs):
        h = hashlib.sha256()
        for n, mh in pairs:
            h.update(n.encode())
            h.update(mh.encode())
        return h.hexdigest()

    monkeypatch.setattr(code_equiv, "SPLITS", {old: (old_h, ((a, ha), (b, hb)))})
    got = engine._collapse_splits(list(mods))
    assert [n for n, _ in got] == ["open_guji_cv.steps.cell_shrink", old, "open_guji_cv.steps.occlusion"]
    assert got[1] == (old, old_h)
    assert digest(got) == digest([(mods[0], _module_source_hash(mods[0])), (old, old_h),
                                  (mods[2], _module_source_hash(mods[2]))])
    monkeypatch.setattr(code_equiv, "SPLITS", {old: (old_h, ((a, ha), (b, "0" * 64)))})
    assert [n for n, _ in engine._collapse_splits(list(mods))] == [engine._fingerprint_name(m) for m in mods]
    monkeypatch.setattr(code_equiv, "SPLITS", {old: (old_h, ((a, ha), ("open_guji_cv.seg.nope", hb)))})
    assert len(engine._collapse_splits(list(mods))) == 4      # 缺一块 → 不合并


def test_split_parts_listed_together_in_every_step():
    """拆分登记的几块：哪个 Step 用了其中一块，就得把几块都列进 code_deps（否则合不回去，产物白白过期）。"""
    for old, (old_h, parts) in code_equiv.SPLITS.items():
        names = {p for p, _ in parts}
        for sid, st in STEPS.items():
            mods = {type(st).__module__, *st.spec.code_deps}
            assert not (mods & names) or names <= mods, f"{sid} 只列了 {old} 拆出来的一部分：{sorted(mods & names)}"
