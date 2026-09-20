# -*- coding: utf-8 -*-
"""格级复用（core/reuse.py）：三道闸 + 逐格几何比对。

用真的 ProductStore / Manifest / Step 对象，只有 RunContext 是鸭子类型的壳——
复用逻辑吃的正是 store、manifest、producer、product 这几样。
"""
from __future__ import annotations

from types import SimpleNamespace

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.engine import self_hash
from open_guji_cv.core.reuse import cell_reuse
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars, PageChars
from open_guji_cv.products.kinds.recog import ColumnMatch, MatchRec, PageMatch
from open_guji_cv.products.manifest import ManifestEntry
from open_guji_cv.products.store import ProductStore

STEP = STEPS["glyph_match"]
UP = STEPS["cell_shrink"]


def _char(i: int, bb: tuple, flags=()) -> CharRec:
    return CharRec(id=f"tb:1:1:{i}", slot=i, pos=i, idx=i - 1, cell_type="char",
                   bbox_col=(0, 0, 10, 10), bbox_page=bb, patch_key=f"p0001c01s{i}",
                   flags=list(flags))


def _chars(recs) -> PageChars:
    return PageChars(page=1, columns=[ColumnChars(col=1, ok=True, n_instances=len(recs), chars=recs)])


def _match(ids) -> PageMatch:
    return PageMatch(page=1, db_fingerprint="x", columns=[ColumnMatch(
        col=1, ok=True, chars=[MatchRec(id=i, slot=int(i.split(":")[-1]), sub=None,
                                        verdict="same", char="甲") for i in ids])])


class _Ctx:
    def __init__(self, store, new_up):
        self.store = store
        self.book = SimpleNamespace(id="tb")
        self.reuse_enabled = True
        self._new_up = new_up
        self.logs = []

    def params_for(self, step):
        return step.spec.params()

    def producer(self, kind):
        return {"char_index": UP, "char_patch": UP}[kind]

    def product(self, kind, page):
        return self._new_up

    def log(self, s):
        self.logs.append(s)


def _setup(tmp_path, old_recs, new_recs, *, self_hash_ok=True):
    store = ProductStore(tmp_path)
    _, sha_up = store.write("tb", "cell_shrink", "p0001", {"char_index": _chars(old_recs)})
    _, sha_own = store.write("tb", "glyph_match", "p0001", {"glyph_match": _match([r.id for r in old_recs])})
    ctx = _Ctx(store, _chars(new_recs))
    sh = self_hash(STEP, ctx.book, ctx.params_for(STEP)) if self_hash_ok else "stale-self"
    store.manifest("tb", "glyph_match").put(ManifestEntry(
        key="p0001", fingerprint="f", sha256=sha_own,
        upstream={"char_index": sha_up, "char_patch": sha_up}, self_hash=sh))
    # 上游重写 → 旧的进 _prev
    store.write("tb", "cell_shrink", "p0001", {"char_index": _chars(new_recs)})
    return ctx


def test_unchanged_cells_are_reused_and_moved_ones_are_not(tmp_path):
    old = [_char(1, (10, 10, 60, 70)), _char(2, (10, 80, 60, 140)), _char(3, (10, 150, 60, 210))]
    new = [_char(1, (10.5, 10, 60, 70.9)),      # 1px 内
           _char(2, (10, 83, 60, 143)),         # 移了 3px
           _char(3, (10, 150, 60, 210), flags=("lost_patch",))]   # 几何同、旗标变
    ctx = _setup(tmp_path, old, new)
    got = cell_reuse(ctx, STEP, 1, "glyph_match")
    assert set(got) == {"tb:1:1:1"}
    assert got["tb:1:1:1"].char == "甲"


def test_prev_generation_is_kept_by_store_write(tmp_path):
    store = ProductStore(tmp_path)
    store.write("tb", "cell_shrink", "p0001", {"char_index": _chars([_char(1, (0, 0, 1, 1))])})
    assert store.prev_sha("tb", "cell_shrink", "p0001") is None
    _, sha1 = store.write("tb", "cell_shrink", "p0001", {"char_index": _chars([_char(1, (0, 0, 2, 2))])})
    assert store.prev_sha("tb", "cell_shrink", "p0001") is not None
    assert store.prev_sha("tb", "cell_shrink", "p0001") != sha1
    assert store.read_prev("tb", "cell_shrink", "p0001", "char_index").columns[0].chars[0].bbox_page == (0, 0, 1, 1)


def test_no_reuse_when_step_itself_changed(tmp_path):
    old = [_char(1, (10, 10, 60, 70))]
    ctx = _setup(tmp_path, old, old, self_hash_ok=False)
    assert cell_reuse(ctx, STEP, 1, "glyph_match") == {}


def test_no_reuse_when_switched_off(tmp_path):
    old = [_char(1, (10, 10, 60, 70))]
    ctx = _setup(tmp_path, old, old)
    ctx.reuse_enabled = False
    assert cell_reuse(ctx, STEP, 1, "glyph_match") == {}


def test_no_reuse_when_recorded_upstream_is_neither_prev_nor_current(tmp_path):
    """manifest 记的上游 sha 既不是 _prev 也不是盘上现在这份——中间又跑过一次上游，
    旧记录是拿另一版上游算的，不认。"""
    old = [_char(1, (10, 10, 60, 70))]
    v71 = [_char(1, (10, 10, 60, 71))]
    v72 = [_char(1, (10, 10, 60, 72))]
    ctx = _setup(tmp_path, old, v71)          # 记的是 old；此时 _prev=old、盘上=v71
    ctx.store.write("tb", "cell_shrink", "p0001", {"char_index": _chars(v72)})   # _prev=v71、盘上=v72
    ctx._new_up = _chars(v72)
    assert cell_reuse(ctx, STEP, 1, "glyph_match") == {}


def test_reuse_when_upstream_not_rewritten_at_all(tmp_path):
    """上游没重写（盘上那份就是 manifest 记的那份）→ 全部复用。"""
    old = [_char(1, (10, 10, 60, 70)), _char(2, (10, 80, 60, 140))]
    store = ProductStore(tmp_path)
    _, sha_up = store.write("tb", "cell_shrink", "p0001", {"char_index": _chars(old)})
    _, sha_own = store.write("tb", "glyph_match", "p0001", {"glyph_match": _match([r.id for r in old])})
    ctx = _Ctx(store, _chars(old))
    store.manifest("tb", "glyph_match").put(ManifestEntry(
        key="p0001", fingerprint="f", sha256=sha_own,
        upstream={"char_index": sha_up}, self_hash=self_hash(STEP, ctx.book, ctx.params_for(STEP))))
    assert set(cell_reuse(ctx, STEP, 1, "glyph_match")) == {"tb:1:1:1", "tb:1:1:2"}


def test_cell_without_page_bbox_is_never_reused(tmp_path):
    old = [CharRec(id="tb:1:1:1", slot=1, pos=1, idx=0, cell_type="char",
                   bbox_col=(0, 0, 10, 10), bbox_page=None, patch_key="k")]
    ctx = _setup(tmp_path, old, old)
    assert cell_reuse(ctx, STEP, 1, "glyph_match") == {}
