# -*- coding: utf-8 -*-
"""形近对表读取/查询的契约（用临时小表，不读仓里那份 620 KB 的真表）。"""

from __future__ import annotations

from open_guji_cv.clustering.confusables import is_pair, load_pairs, near_forms


def _table(tmp_path):
    f = tmp_path / "pairs.tsv"
    f.write_text("# 表头\na\tb\tkind\tcos\tdetail\n"
                 "諭\t論\tslot\t0.958\t⿰:R:俞/侖\n"
                 "己\t巳\tvisual\t0.947\t\n"
                 "論\t倫\tslot\t0.950\t⿰:L:言/亻\n", encoding="utf-8")
    return f


def test_symmetric_and_sorted(tmp_path):
    f = _table(tmp_path)
    load_pairs.cache_clear()
    t = load_pairs(f)
    assert [x[0] for x in t["論"]] == ["諭", "倫"]          # 两边都能查到，按 cos 降序
    assert is_pair("巳", "己", f) and not is_pair("己", "論", f)
    nf = near_forms("諭", k=3, path=f)
    assert nf == [{"char": "論", "kind": "slot", "cos": 0.958, "detail": "⿰:R:俞/侖"}]
    assert near_forms("論", k=1, within={"倫"}, path=f)[0]["char"] == "倫"
    assert near_forms("人", path=f) == []


def test_missing_table_is_empty(tmp_path):
    load_pairs.cache_clear()
    assert load_pairs(tmp_path / "nope.tsv") == {} and near_forms("諭", path=tmp_path / "nope.tsv") == []
