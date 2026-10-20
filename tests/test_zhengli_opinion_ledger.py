# -*- coding: utf-8 -*-
"""scripts/zhengli/opinion_ledger.py（M10·D3 意见台账，GUJI-690）：自造数据，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "opinion_ledger.py"
spec = importlib.util.spec_from_file_location("opinion_ledger_under_test", P)
ol = importlib.util.module_from_spec(spec)
sys.modules["opinion_ledger_under_test"] = ol
spec.loader.exec_module(ol)


def op(a, choice, char=None, voter="v1", note="", vol="001"):
    return {"book": "96mid1ogzk", "vol": vol, "a": a, "rev": "001-r2", "choice": choice, "char": char,
            "voter": voter, "note": note, "ts": 1}


def ev(cell, v, *, shape=None, quality=None, source=None, opinion_ids=None, ts="2026-10-18T00:00:00Z", eid=None):
    pl = {"v": v}
    for k, x in (("shape", shape), ("quality", quality), ("source", source), ("opinion_ids", opinion_ids)):
        if x is not None:
            pl[k] = x
    return {"id": eid or f"e-{cell}-{v}", "ts": ts, "kind": "confirm", "actor": "user", "payload": pl,
            "target": {"unit": "cell", "key": f"vol01:{cell}", "book": "vol01"}}


def test_statuses():
    snap = [
        op("9:7:17", "char", "曾", voter="t", note="【测试】Eden", vol="vol01"),
        op("9:7:17", "char", "臼", voter="a"),                       # 被 source 引用 → adopted
        op("9:7:17", "char", "臼", voter="b"),                       # 同格已有人裁且一致 → consistent
        op("9:7:17", "char", "曰", voter="c"),                       # 不一致 → overridden
        op("10:7:10", "cut", voter="a"),                             # opinion_ids 引用 → adopted
        op("20:1:1", "unsure", voter="a"),                           # abstained
        op("30:1:1", "none", voter="a"),                             # 没人处理 → open
        op("40:1:1", "cut", voter="d"),                              # 切分没问题（clean）不算人裁 → open
    ]
    events = [
        ev("9:7:17", "confirm", shape="臼", source="网站公众意见（001-r2；意见 96mid1ogzk:001:9:7:17:a）", eid="E1"),
        ev("10:7:10", "seg_defect", quality="truncated", opinion_ids=["96mid1ogzk:001:10:7:10:a"], eid="E2"),
        ev("40:1:1", "seg_defect", quality="clean", eid="E3"),
    ]
    rows = {r["opinion_id"].split(":", 2)[2]: r for r in ol.build(snap, events)}
    assert rows["9:7:17:t"]["status"] == "test"
    assert rows["9:7:17:a"]["status"] == "adopted" and rows["9:7:17:a"]["event_id"] == "E1"
    assert rows["9:7:17:b"]["status"] == "consistent"
    assert rows["9:7:17:c"]["status"] == "overridden"
    assert rows["10:7:10:a"]["status"] == "adopted" and rows["10:7:10:a"]["event_id"] == "E2"
    assert rows["20:1:1:a"]["status"] == "abstained"
    assert rows["30:1:1:a"]["status"] == "open"
    assert rows["40:1:1:d"]["status"] == "open"


def test_cli_strict(tmp_path):
    snap = tmp_path / "001-r2.jsonl"
    snap.write_text(json.dumps(op("30:1:1", "none")) + "\n", encoding="utf-8")
    evs = tmp_path / "e.jsonl"
    evs.write_text("", encoding="utf-8")
    out = tmp_path / "state.jsonl"
    assert ol.main(["--snapshot", str(snap), "--events", str(evs), "--out", str(out), "--strict"]) == 3
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "open"
