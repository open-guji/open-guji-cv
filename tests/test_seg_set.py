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


def test_code_hash_unchanged_until_code_moves():
    """搬家前 SERIES_MODULES 为空：带不带 book，各步代码指纹逐位相同（现有产物不过期）。"""
    if S.SERIES_MODULES:
        pytest.skip("代码已搬进套书目录，指纹按套书算")
    import open_guji_cv.steps  # noqa: F401  注册各步
    for sid in ("border_detect", "row_segment", "cell_shrink"):
        step = STEPS[sid]
        assert code_hash(step) == code_hash(step, book=make_book())
        assert code_hash(step) == code_hash(step, book=make_book(seg_set="shiji_wyg"))
