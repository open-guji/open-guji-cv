# -*- coding: utf-8 -*-
"""列端回归 fixture(`tests/fixtures/colend/`,vol02 B 批 231 端,见该目录 README)。

这里只钉两件事,**不断言规则好不好**(质量归 `research/colend_eval/eval_fixture.py`):
1. fixture 自身完整(文件在、条数/列数对、标签取值合法、每端的列都在);
2. **行为钉子**:对冻结的整列跑现行 `clean_column`,每端的 `(档位, 削行数)` 与冻结时一致。
   改 `column_border_trim` / `second_layer` / `strip_column_rules` / `denoise_column` 之后这条变红,
   说明列端行为变了——要么是预期的(同时更新冻结值并在 PR 写清谁变了),要么是回归。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.books.siku_zongmu.column import clean_column

COLEND = Path(__file__).resolve().parent / "fixtures" / "colend"
LABELS = {"none", "trim", "double", "glued"}


@pytest.fixture(scope="module")
def man() -> dict:
    return json.loads((COLEND / "manifest.json").read_text(encoding="utf-8"))


def test_fixture_integrity(man):
    assert len(man["ends"]) == 231
    assert len(man["columns"]) == 224
    assert len({e["id"] for e in man["ends"]}) == 231
    assert {e["label"] for e in man["ends"]} <= LABELS
    assert Counter(e["label"] for e in man["ends"])["glued"] == 18
    for k, c in man["columns"].items():
        assert (COLEND / c["file"]).is_file(), k
    for e in man["ends"]:
        assert e["col_key"] in man["columns"]
        assert e["end"] in ("top", "bot")


def test_frozen_end_behaviour(man):
    """冻结整列 → 现行 clean_column → 每端 (case, px) 与冻结一致。"""
    layers, gap = tuple(man["layers"]), tuple(man["layer_gap"])
    by_col: dict[str, list[dict]] = {}
    for e in man["ends"]:
        by_col.setdefault(e["col_key"], []).append(e)
    bad = []
    for key, ends in by_col.items():
        c = man["columns"][key]
        img = np.where(np.array(Image.open(COLEND / c["file"]).convert("L")) >= 128, 255, 0).astype(np.uint8)
        _, diag = clean_column(img, layers=layers, layer_gap=gap, inner_bottom=c["inner_bottom"])
        for e in ends:
            d = diag["top" if e["end"] == "top" else "bottom"]
            if (d["case"], int(d["px"])) != (e["frozen_case"], e["frozen_px"]):
                bad.append((e["id"], (e["frozen_case"], e["frozen_px"]), (d["case"], int(d["px"]))))
    assert not bad, f"{len(bad)} 端的列端行为变了(id, 冻结, 现在): {bad[:10]}"
