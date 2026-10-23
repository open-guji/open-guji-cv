# -*- coding: utf-8 -*-
"""ops/text_diff.py（`guji char-diff`，1.0 标准 G2）：两份 char 逐格比。"""
from __future__ import annotations

from open_guji_cv.ops import text_diff as TD


def _doc(cells):
    return {"pages": [{"page": 1, "columns": [{"col": 1, "cells": cells}]}]}


def test_same():
    a = _doc([{"a": "1:1:1", "c": "天"}])
    assert TD.diff(a, a)["n"] == 0 and TD.summary(TD.diff(a, a)) == "逐格相同"


def test_fields_and_structure(tmp_path):
    text = _doc([{"a": "1:1:1", "c": "天"}, {"a": "1:1:2a", "c": "子", "lane": "a"}, {"a": "1:1:3", "c": "□", "lacuna": True}])
    frozen = _doc([{"a": "1:1:1", "c": "夫"}, {"a": "1:1:2", "c": "子"}, {"a": "1:1:3", "c": "□"}])
    res = TD.diff(text, frozen)
    assert res["only_text"] == ["1:1:2a"] and res["only_frozen"] == ["1:1:2"]
    assert [d["a"] for d in res["changed"]] == ["1:1:1", "1:1:3"]
    assert res["changed"][0]["c"] == ("夫", "天") and res["changed"][1]["lacuna"] == (None, True)
    assert res["n"] == 4
    out = tmp_path / "d.tsv"
    TD.write_tsv(res, text, frozen, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("格\t") and len(lines) == 5
