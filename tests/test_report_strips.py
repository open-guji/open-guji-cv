# -*- coding: utf-8 -*-
"""`report/strips.py`：对勘差异的截条图，落盘成 webp 文件、写回 `strip` 相对路径。

用 fixture 册 `keben`（`ws` fixture）+ 手造的 Step3/Step7 产物 + 预置进
`ImageCache` 的字块图（`ImageCache.put`）——绕开真正跑 Step1-4，因为
`RunContext.materialize` 缓存命中就直接返回，不会调用 `step.render()`
现算（那需要列图/版框等一整条上游产物，不是这个模块要测的东西）。
"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
from open_guji_cv.products.store import ProductStore
from open_guji_cv.report.strips import write_diff_strips, write_variant_thumbs

BOOK, PAGE, COL = "keben", 1, 1


def _cell(slot: int) -> CellRec:
    return CellRec(slot=slot, pos=slot, y0=0, y1=10, x0=0, x1=10, kind="char", order=slot)


def _rec(slot: int, char: str, *, admit=False, human=False) -> AdmitRec:
    return AdmitRec(id=f"{BOOK}:{PAGE}:{COL}:{slot}", slot=slot, admit=admit, char=char,
                    channel=("human" if human else None))


def _seed_products(ws) -> ProductStore:
    """三个字位（1/2/3），Step3 有格、Step7 有裁决——`page_slots` 拼得出字位流。"""
    store = ProductStore()
    cells = PageCells(page=PAGE, period=None, ref_w=None, columns=[ColumnCells(
        col=COL, ok=True, n_body_slots=3,
        cells=[_cell(1), _cell(2), _cell(3)])])
    admit = PageAdmit(page=PAGE, columns=[ColumnAdmit(
        col=COL, ok=True,
        chars=[_rec(1, "甲"), _rec(2, "乙", admit=True), _rec(3, "丙")])])
    store.write(BOOK, "row_segment", f"p{PAGE:04d}", {"cells": cells})
    store.write(BOOK, "seed_admit", f"p{PAGE:04d}", {"seed_admit": admit})
    return store


def _seed_images(tiny=(20, 16)) -> ImageCache:
    """给三个字位各放一张假字块图（`ImageCache.materialize` 缓存命中就不现算）。"""
    cache = ImageCache()
    for slot in (1, 2, 3):
        img = np.full(tiny, 40 + slot * 10, np.uint8)
        cache.put(BOOK, "char_patch", f"p{PAGE:04d}c{COL:02d}s{slot}", img)
    return cache


def _diff(slot: int, kind: str, **kw) -> dict:
    d = {"id": f"{BOOK}:{PAGE}:{COL}:{slot}", "page": PAGE, "col": COL, "slot": slot,
        "sub": None, "kind": kind, "char": "甲", "ref": "乙", "witness": "证人甲",
        "channel": None, "admit": False, "human": False, "n": 1, "hyp_ctx": "",
        "ref_ctx": "", "grade": "suspect", "strip": None}
    d.update(kw)
    return d


@pytest.fixture
def seeded(ws):
    store = _seed_products(ws)
    cache = _seed_images()
    return store, cache


def test_writes_a_webp_file_and_sets_relative_path(tmp_path, seeded):
    store, cache = seeded
    doc = {"book": BOOK, "diffs": [_diff(2, "sub.other")]}
    stats = write_diff_strips(doc, tmp_path / "out", store=store, cache=cache)
    assert stats == {"证人甲": 1}
    rel = doc["diffs"][0]["strip"]
    assert rel == "strips/证人甲/keben_1_1_2.webp"
    assert (tmp_path / "out" / rel).exists()
    assert (tmp_path / "out" / rel).stat().st_size > 0


def test_only_substitution_and_unreadable_kinds_get_strips(tmp_path, seeded):
    """增删（missing/extra）与异体（variant.*）不出整条截图——见模块头。"""
    store, cache = seeded
    doc = {"book": BOOK, "diffs": [_diff(1, "missing"), _diff(3, "variant.other")]}
    stats = write_diff_strips(doc, tmp_path / "out", store=store, cache=cache)
    assert stats == {}
    assert all(d["strip"] is None for d in doc["diffs"])


def test_limit_stops_after_n_strips(tmp_path, seeded):
    store, cache = seeded
    doc = {"book": BOOK, "diffs": [_diff(1, "sub.other"), _diff(2, "sub.other"),
                                   _diff(3, "unreadable")]}
    stats = write_diff_strips(doc, tmp_path / "out", store=store, cache=cache, limit=1)
    assert sum(stats.values()) == 1
    n_set = sum(1 for d in doc["diffs"] if d["strip"])
    assert n_set == 1


def test_variant_thumbs_grouped_by_pair(tmp_path, seeded):
    store, cache = seeded
    doc = {"book": BOOK, "diffs": [_diff(1, "variant.to_orthodox", char="甲", ref="乙"),
                                   _diff(2, "variant.to_orthodox", char="甲", ref="乙")]}
    stats = write_variant_thumbs(doc, tmp_path / "out", store=store, cache=cache)
    assert stats == {"证人甲": 2}
    ex = doc["variant_examples"]["证人甲"]["甲\t乙"]
    assert len(ex) == 2
    assert all((tmp_path / "out" / p).exists() for p in ex)
