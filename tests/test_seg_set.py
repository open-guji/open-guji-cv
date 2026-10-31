# -*- coding: utf-8 -*-
"""套书登记（core/seg_set）：推导、校验、指纹在搬家前不变。"""
import pytest

from open_guji_cv.core import seg_set as S
from open_guji_cv.core.engine import code_hash
from open_guji_cv.core.step import STEPS
from tests.helpers import make_book


def test_seg_set_derived_from_pipeline():
    assert S.seg_set_of(make_book()) == "siku_zongmu"
    assert S.seg_set_of(make_book(pipeline="keben_free")) == "zengguang_youxue"
    assert S.seg_set_of(make_book(pipeline="modern_body")) == "beixing"


def test_seg_set_explicit_wins():
    assert S.seg_set_of(make_book(seg_set="shiji_wyg")) == "shiji_wyg"


def test_unknown_seg_set_rejected():
    with pytest.raises(ValueError):
        S.validate_seg_set("nope")


def test_code_hash_unchanged_for_books_without_override():
    """没有覆盖的套书：带不带 book，各步代码指纹逐位相同（现有产物不过期）。"""
    import open_guji_cv.steps  # noqa: F401  注册各步
    for sid in ("border_detect", "row_segment", "cell_shrink"):
        step = STEPS[sid]
        assert code_hash(step) == code_hash(step, book=make_book())


def test_shiji_row_segment_fingerprint_is_its_own():
    """史記覆盖了职名页实现：row_segment 的指纹换成史記自己的模块，不再受殿本同名模块影响；别的步不变。"""
    import open_guji_cv.steps  # noqa: F401
    sj, dian = make_book(seg_set="shiji_wyg"), make_book()
    rs = STEPS["row_segment"]
    assert code_hash(rs, book=sj) != code_hash(rs, book=dian)
    assert S.replace_deps(sj, ["open_guji_cv.books.siku_zongmu.roster_segment", "open_guji_cv.seg.seam"]) == \
        ["open_guji_cv.books.shiji_wyg.roster_segment", "open_guji_cv.seg.seam"]
    for sid in ("border_detect", "cell_shrink", "column_warp"):
        assert code_hash(STEPS[sid], book=sj) == code_hash(STEPS[sid])


def test_resolve_picks_override_for_shiji_only():
    d = "open_guji_cv.books.siku_zongmu.roster_segment"
    assert S.resolve(make_book(), d) == d
    assert S.resolve(make_book(seg_set="shiji_wyg"), "open_guji_cv.books.shiji_wyg.roster_segment") == \
        "open_guji_cv.books.shiji_wyg.roster_segment"
    assert S.resolve(make_book(seg_set="shiji_wyg"), d) == "open_guji_cv.books.shiji_wyg.roster_segment"
