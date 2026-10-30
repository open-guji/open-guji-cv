# -*- coding: utf-8 -*-
"""Step3 切线回归 fixture(`tests/fixtures/cutline/`,vol02 A 批 196 条切线金标 + 3 个矮格,见该目录 README)。

只钉两件事,**不断言切线好不好**(质量归 `research/cutline_eval/eval_cutlines.py`):
1. fixture 完整:文件在、条数对、冻结数据自洽(金标与冻结现役切点的一致数、矮格确实是矮格);
2. **行为钉子(rule-only,不需要 torch)**:对冻结的列图跑现行 `segment_column(cut_judge=None)`,
   boundaries 与冻结的 rule-only 结果逐点一致。改 `row_boundaries`/`seam`/`jiazhu_split` 的规则路径后变红 = Step3 行为变了
   (预期的就重跑 `research/cutline_eval/build_fixture_cuts.py` 更新冻结值并在 PR 写清;否则是回归)。
   U-Net 裁判路径(现役)不在这里钉:它要 torch 与权重,缺件时是**跳过不是通过**——有环境时用 `eval_cutlines.py` 对账。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
from open_guji_cv.books.siku_zongmu.row_boundaries import segment_column

CUT = Path(__file__).resolve().parent / "fixtures" / "cutline"


@pytest.fixture(scope="module")
def man() -> dict:
    return json.loads((CUT / "manifest.json").read_text(encoding="utf-8"))


def _img(c: dict) -> np.ndarray:
    return np.where(np.array(Image.open(CUT / c["file"]).convert("L")) >= 128, 255, 0).astype(np.uint8)


def test_fixture_integrity(man):
    assert len(man["gold"]) == 196 and len(man["columns"]) == 178
    for c in man["columns"].values():
        assert (CUT / c["file"]).is_file()
    for g in man["gold"]:
        assert f"p{g['page']}_c{g['col']}" in man["columns"]
    # 冻结的现役切点与金标 ≤3px 一致的条数(A 批 194/196):这是**冻结数据**的自洽检查,不是对引擎的断言
    assert sum(abs(g["y_gold"] - g["y_frozen"]) <= 3 for g in man["gold"]) == 194
    # 矮格:高 < 0.6×period
    for pg, col, slot in man["runt_cells"]:
        c = man["columns"][f"p{pg}_c{col}"]; b = c["frozen_boundaries"]; nr = c["segment_kwargs"]["n_raised"]
        h = b[slot + nr] - b[slot + nr - 1]
        assert h < 0.6 * c["segment_kwargs"]["period"], (pg, col, slot, h)


def test_frozen_rule_only_behaviour(man):
    bad = []
    for key, c in man["columns"].items():
        r = segment_column(_img(c), cut_judge=None, **c["segment_kwargs"], **c["run_kwargs"])
        got = None if r is None else [round(float(x), 1) for x in r.boundaries]
        exp = c["frozen_rule_boundaries"]
        if got is None or exp is None or len(got) != len(exp) or max(abs(a - b) for a, b in zip(got, exp)) > 0.5:
            bad.append(key)
    assert not bad, f"{len(bad)} 列的 rule-only 切点变了: {bad[:10]}"
