"""行列识别统一格式 + 评测的单测。"""

import json

import pytest

from open_guji_cv.clustering.layout_eval import compare_page, evaluate, format_report
from open_guji_cv.clustering.layout_spec import (ColumnSpec, PageLayout,
                                                  from_char_grid)


def _page(book="b", page="1", layouts=("rigid",)*3, n_chars=(21, 21, 21),
          page_class=None):
    cols = [ColumnSpec(index=len(layouts)-i, left_x=i*100.0,
                       right_x=i*100.0+90, layout=l, n_chars=n)
            for i, (l, n) in enumerate(zip(layouts, n_chars))]
    return PageLayout(book=book, page=page,
                      image_size={"width": 900, "height": 2000},
                      n_cols=len(cols), cell_h=110.0, columns=cols,
                      page_class=page_class)


def test_column_rejects_unknown_layout():
    with pytest.raises(ValueError):
        ColumnSpec(index=1, left_x=0, right_x=1, layout="springy", n_chars=1)


def test_derived_page_class():
    assert _page(layouts=("rigid",)*3).derived_page_class() == "body"
    assert _page(layouts=("elastic",)*3).derived_page_class() == "roster"
    assert _page(layouts=("rigid", "elastic", "rigid")).derived_page_class() == "mixed"


def test_roundtrip(tmp_path):
    p = _page(layouts=("rigid", "elastic", "rigid"), n_chars=(21, 5, 18))
    f = tmp_path / "a.json"
    p.save(f)
    q = PageLayout.load(f)
    assert q.n_cols == 3
    assert [c.layout for c in q.columns] == [c.layout for c in p.columns]
    assert [c.n_chars for c in q.columns] == [c.n_chars for c in p.columns]
    # page_class 落盘时固化为导出值
    assert json.loads(f.read_text(encoding="utf-8"))["page_class"] == "mixed"


def test_from_char_grid_maps_spread_col_and_counts_ink_cells():
    grid = {
        "image_size": {"width": 900, "height": 2000},
        "grid": {"cell_h": 110.0},
        "columns": [
            {"index": 2, "left_x": 0.0, "right_x": 90.0, "spread_col": True,
             "cells": [{"type": "char"}, {"type": "char"}, {"type": "empty"}]},
            {"index": 1, "left_x": 100.0, "right_x": 190.0,
             "cells": [{"type": "char"}] * 21},
            {"index": 3, "left_x": 200.0, "right_x": 290.0,
             "skipped": "non_text_column", "cells": []},
        ],
    }
    pl = from_char_grid(grid, "vol01", "7")
    assert pl.n_cols == 2                      # skipped 列不计入
    assert [c.index for c in pl.columns] == [2, 1]   # 从右到左：index 降序
    assert pl.columns[0].layout == "elastic" and pl.columns[0].n_chars == 2
    assert pl.columns[1].layout == "rigid" and pl.columns[1].n_chars == 21


def test_compare_page_counts_confusion_and_char_error():
    gold = _page(layouts=("rigid", "elastic", "rigid"), n_chars=(21, 5, 18))
    pred = _page(layouts=("rigid", "rigid", "elastic"), n_chars=(21, 13, 18))
    r = compare_page(gold, pred)
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (0, 1, 1, 1)
    assert r["n_chars_exact"] == 2
    assert r["n_chars_abs_err"] == 8


def test_evaluate_stratifies_by_page_class():
    body_g = _page(page="1", layouts=("rigid",)*3)
    body_p = _page(page="1", layouts=("rigid",)*3)
    ros_g = _page(page="2", layouts=("elastic",)*3, n_chars=(5, 6, 7))
    ros_p = _page(page="2", layouts=("elastic", "rigid", "elastic"),
                  n_chars=(5, 21, 7))
    rep = evaluate([(body_g, body_p), (ros_g, ros_p)])
    assert set(rep["by_page_class"]) == {"body", "roster"}
    assert rep["by_page_class"]["body"]["layout_acc"] == 1.0
    # roster 页 3 列里漏判 1 列 elastic
    assert rep["by_page_class"]["roster"]["elastic_recall"] == pytest.approx(2/3, abs=1e-4)
    assert "elastic P/R/F1" in format_report(rep)


def test_all_rigid_baseline_gets_zero_f1_despite_high_accuracy():
    """全判 rigid 能拿高准确率但 F1=0——这正是主指标取 F1 的原因。"""
    gold = _page(layouts=("rigid",)*9 + ("elastic",), n_chars=(21,)*9 + (5,))
    pred = _page(layouts=("rigid",)*10, n_chars=(21,)*10)
    rep = evaluate([(gold, pred)])
    o = rep["overall"]
    assert o["layout_acc"] == 0.9        # 看着很高
    assert o["elastic_f1"] == 0.0        # 实则完全没用


def test_blank_and_uncertain_are_skipped_in_metrics():
    """空列/存疑列不进分类指标——防止把标注状态当成第三种排版去算对错。"""
    gold = _page(layouts=("rigid", "blank", "uncertain", "elastic"),
                 n_chars=(21, 0, 0, 5))
    pred = _page(layouts=("rigid", "elastic", "elastic", "elastic"),
                 n_chars=(21, 3, 9, 5))
    r = compare_page(gold, pred)
    assert r["n_skipped"] == 2
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 0, 0, 1)


def test_derived_page_class_ignores_blank_columns():
    p = _page(layouts=("rigid", "rigid", "blank"), n_chars=(21, 21, 0))
    assert p.derived_page_class() == "body"
    p2 = _page(layouts=("blank", "blank", "blank"), n_chars=(0, 0, 0))
    assert p2.derived_page_class() == "cover"


def test_n_chars_optional_skips_char_metrics():
    """金标不标字数时，字数指标为 None 而不是被当成 0 拉低分数。"""
    gold = _page(layouts=("rigid", "elastic"), n_chars=(None, None))
    pred = _page(layouts=("rigid", "elastic"), n_chars=(21, 5))
    rep = evaluate([(gold, pred)])
    o = rep["overall"]
    assert o["layout_acc"] == 1.0
    assert o["n_chars_exact_rate"] is None
    assert "字数未标" in format_report(rep)
