# -*- coding: utf-8 -*-
"""人工指定格分片的检查与宽松读取（M10·D5，GUJI-692）：自造分片，不碰真书。"""
from __future__ import annotations

import json

from open_guji_cv.feedback import consumers, lookup
from open_guji_cv.gold.store import GoldStore

CELLS = [{"slot": 1, "sub": "", "kind": "char", "y0": 0, "y1": 10, "x0": 0, "x1": 8},
         {"slot": 2, "sub": "", "kind": "char", "y0": 10, "y1": 20, "x0": 0, "x1": 8}]


def item(page, col, cells=CELLS, history=None):
    return {"id": f"vol01:{page}:{col}", "anchor": {"book": "vol01", "page": page, "col": col},
            "expected": {"cells": cells}, "label_origin": "human", "status": "active",
            "history": history if history is not None else [{"ts": "2026-10-20T00:00:00Z", "change": "定框", "why": "职名页"}]}


def test_check_reports_each_problem(tmp_path):
    p = tmp_path / "items.jsonl"
    rows = [
        item(89, 7),
        item(89, 9, history=[{"ts": "2026-10-20T00:00:00Z", "change": "定框"}]),            # 缺 why
        item(90, 2, cells=[{"slot": 1, "kind": "big", "y0": 5, "y1": 1, "x0": 0, "x1": 8}]),  # kind 不认识、框反了
        item(90, 6, cells=[dict(CELLS[0]), dict(CELLS[0])]),                                 # 格号重复
        item(89, 7),                                                                          # 同一列两行
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n{坏行\n", encoding="utf-8")
    probs = lookup.check_manual_cells(p)
    text = "\n".join(probs)
    assert "第 2 行：history[0] 缺 why" in text
    assert "kind='big' 不认识" in text and "框不对" in text
    assert "格号 1 重复" in text
    assert "与第 1 行是同一列" in text
    assert "第 6 行：不是 JSON" in text
    assert not any(x.startswith("第 1 行") for x in probs)


def test_resolved_manual_cells_skips_bad_line_loudly(tmp_path, monkeypatch, capsys):
    store = GoldStore(tmp_path)
    path = store.items_path(lookup.MANUAL_CELLS_SHARD)
    path.parent.mkdir(parents=True, exist_ok=True)
    bad = item(89, 9, history=[{"why": "缺 ts 和 change"}])                 # 信封不合法：以前整个分片作废
    path.write_text(json.dumps(item(89, 7), ensure_ascii=False) + "\n" + json.dumps(bad, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    monkeypatch.setattr(consumers, "verdict_store", lambda: store)
    out = lookup.resolved_manual_cells("vol01")
    assert list(out) == [(89, 7)]                                            # 好的那列照样生效
    assert "第 2 行格式不对" in capsys.readouterr().err
