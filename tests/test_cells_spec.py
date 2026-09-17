# -*- coding: utf-8 -*-
"""`pages=cells:<坐标>` 的解析（Step7「按坐标查卡」，用户 2026-09-17）。"""
import pytest

from open_guji_cv.review.cards import parse_cells_spec


def test_single_cell_gets_book_prefix():
    assert parse_cells_spec("cells:4:1:21", "bxgb") == {"bxgb:4:1:21"}


def test_multiple_separators():
    """逗号 / 空格 / 中文逗号都当分隔符——人从别处粘坐标进来，分隔符什么都有。"""
    want = {"bxgb:4:1:21", "bxgb:6:8:1"}
    for spec in ("cells:4:1:21,6:8:1", "cells:4:1:21 6:8:1", "cells:4:1:21，6:8:1",
                 "cells: 4:1:21 , 6:8:1 "):
        assert parse_cells_spec(spec, "bxgb") == want


def test_explicit_book_kept():
    """已经带书号的原样保留，不再补一次前缀。"""
    assert parse_cells_spec("cells:bxgb:4:14:1", "bxgb") == {"bxgb:4:14:1"}


def test_sub_suffix_kept():
    """夹注半格 `a`/`b` 后缀要留着——它是 id 的一部分，剥了就对不上那张卡。"""
    assert parse_cells_spec("cells:4:1:21a", "bxgb") == {"bxgb:4:1:21a"}


@pytest.mark.parametrize("spec", ["cells:", "cells:   ", "cells:,,"])
def test_empty_rejected(spec):
    with pytest.raises(ValueError):
        parse_cells_spec(spec, "bxgb")


@pytest.mark.parametrize("spec", ["cells:4:1", "cells:abc", "cells:x:1:21"])
def test_malformed_rejected(spec):
    """宁可报错也不静默出 0 张卡：空面板分不清「没问题」还是「坐标写错了」。"""
    with pytest.raises(ValueError):
        parse_cells_spec(spec, "bxgb")
