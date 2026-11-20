# -*- coding: utf-8 -*-
"""搬家登记（core/code_equiv.MOVED）的守卫：切分代码搬进 books/<套书>/ 后，产物指纹不变。"""
import importlib
import importlib.util

import open_guji_cv.steps  # noqa: F401  注册全部 Step
from open_guji_cv.core import code_equiv
from open_guji_cv.core.engine import _fingerprint_name, _module_source_hash
from open_guji_cv.core.step import STEPS


def _exists(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except ModuleNotFoundError:          # 父包已不在（又搬过一次）
        return False


def _live():
    """还在的搬家登记（又搬过一次的旧项留作历史：它的新名字是后一项的旧名字）。"""
    return {n: v for n, v in code_equiv.MOVED.items() if _exists(n)}


def test_moved_modules_are_gone_from_old_place_and_live_in_books():
    olds = {o for o, _ in code_equiv.MOVED.values()}
    for new, (old, h) in code_equiv.MOVED.items():
        assert new.startswith(("open_guji_cv.books.", "open_guji_cv.seg.", "open_guji_cv.impl")), new
        assert _exists(new) or new in olds, f"{new} 不存在，也不是后一次搬家的旧名"
        assert not _exists(old), f"{old} 搬走后旧位置还留着文件"
        assert len(h) == 64


def test_moved_modules_are_in_some_step_fingerprint():
    mods = {m for st in STEPS.values() for m in (type(st).__module__, *st.spec.code_deps)}
    for new in _live():
        assert new in mods, f"{new} 不在任何 Step 的指纹里，登记它没用"


def test_fingerprint_name_follows_moved_code():
    """代码仍是搬家时那一版 → 指纹里用旧名（搬过几次就沿链走到头）；之后改过 → 用新名（产物照常过期）。"""
    for new, (old, h) in _live().items():
        cur = _module_source_hash(new)
        want = new
        while want in code_equiv.MOVED and code_equiv.MOVED[want][1] == cur:
            want = code_equiv.MOVED[want][0]
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
        # 书仓模块（guji_book.*）由 seg_set.resolve 换进模块表，不在 code_deps 里，不查
        names = {p for p, _ in parts if not p.startswith("guji_book.")}
        for sid, st in STEPS.items():
            mods = {type(st).__module__, *st.spec.code_deps}
            assert not (mods & names) or names <= mods, f"{sid} 只列了 {old} 拆出来的一部分：{sorted(mods & names)}"
