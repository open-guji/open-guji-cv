"""导出：看图判错待人审的放行格记 review=pending（GUJI-555 Lucian 核账：导出口径差 24 格里 12 格）。"""
from __future__ import annotations

import copy

import pytest

from open_guji_cv.formats import guji_page as gp
from open_guji_cv.formats.guji_page_cv import from_cv_products
from open_guji_cv.products.store import ProductStore
from test_guji_page_format import BOOK, META, PAGE, _write


@pytest.fixture
def store(tmp_path):
    st = ProductStore(tmp_path / "products")
    _write(st)
    return st


def _export(store, **kw):
    return from_cv_products(store, BOOK, PAGE, copy.deepcopy(META), **kw)


def _auto_cell(page):
    g = next(x for x in page["glyphs"] if x["review"] == "auto")
    return g["cv_id"]


def test_without_pending_ids_output_is_unchanged(store):
    base = _export(store)
    assert _export(store, pending_ids=None) == base
    assert _export(store, pending_ids=frozenset()) == base
    assert _export(store, pending_ids={"no-such-cell"}) == base


def test_admitted_cell_with_vision_flag_is_exported_as_pending(store):
    base = _export(store)
    cid = _auto_cell(base)
    out = _export(store, pending_ids={cid})
    g = next(x for x in out["glyphs"] if x["cv_id"] == cid)
    g0 = next(x for x in base["glyphs"] if x["cv_id"] == cid)
    assert g["review"] == "pending" and "vision_flag" in g["flags"]
    assert g["method"] == g0["method"]                        # 通道不变，只是不再算已校对
    assert gp.check(out) == []
    # 其余格逐个不变
    rest = lambda p: [x for x in p["glyphs"] if x["cv_id"] != cid]   # noqa: E731
    assert rest(out) == rest(base)


def test_human_decided_cell_is_never_demoted_to_pending(store):
    """人裁过的格不在 pending 集合里（`vision_pending` 已排除）；万一传进来也不降级。"""
    base = _export(store)
    humans = [x["cv_id"] for x in base["glyphs"] if x["review"] == "human"]
    if not humans:
        pytest.skip("夹具里没有人裁格")
    out = _export(store, pending_ids=set(humans))
    assert all(x["review"] == "human" for x in out["glyphs"] if x["cv_id"] in humans)


def test_vision_pending_ids_is_empty_without_vision_records(ws):
    from open_guji_cv.feedback.vision import vision_pending_ids
    assert vision_pending_ids("keben", [1, 2, 3]) == frozenset()
