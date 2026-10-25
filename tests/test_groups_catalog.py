# -*- coding: utf-8 -*-
"""字组总表与状态报告（2026-10-24，sheldon「形近字处理规范化」）：总表由注册表生成、不许过期；
状态报告的计数口径（出现格、组判、人裁核对与码位归一）用自造产物验。"""

from __future__ import annotations

import json


def test_table_is_generated_from_registry_and_up_to_date():
    """改了 `groups/registry.py` 就要跑 `python -m open_guji_cv.groups.catalog` 重生成 `doc/字组/字组总表.md`。"""
    from open_guji_cv.groups import catalog
    from open_guji_cv.groups import registry as R

    assert catalog.OUT.read_text(encoding="utf-8") == catalog.render()
    rs = catalog.rows()
    assert [r["id"] for r in rs] == list(R.FLOW_GROUPS)
    assert {r["kind"] for r in rs} == {"同义", "不同义"}      # 类型只分两类（sheldon 10-24）


def _page(tmp_path, root, book, chars):
    p = tmp_path / root / book / "seed_admit"
    p.mkdir(parents=True, exist_ok=True)
    (p / "p0001.json").write_text(json.dumps({"seed_admit": {"columns": [{"chars": chars}]}}, ensure_ascii=False),
                                  encoding="utf-8")


def test_status_counts_occurrence_flow_and_label_check(tmp_path):
    from open_guji_cv.eval import group_status as S

    grp = lambda pick: {"group": {"id": "ry", "pick": pick, "decision": "keep" if pick else "abstain"}}  # noqa: E731
    _page(tmp_path, "prod", "vol01", [
        {"id": "vol01:1:1:1", "char": "日", "admit": True, "channel": "match_ref", "evidence": grp("日")},
        {"id": "vol01:1:1:2", "char": "曰", "admit": False, "channel": None, "evidence": grp(None)},
        {"id": "vol01:1:1:3", "char": "曰", "admit": True, "channel": "dual", "evidence": {}},
        {"id": "vol01:1:1:4", "char": "旨", "admit": True, "channel": "match_solo", "evidence": {}},
        {"id": "vol01:1:1:5", "char": "刊", "admit": True, "channel": "match_ref", "evidence": {}},
        {"id": "vol01:1:1:6", "char": "人", "admit": True, "channel": "human", "evidence": {}},
    ])
    labels = tmp_path / "unified.jsonl"
    labels.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"id": "vol01:1:1:3", "kind": "shape", "form": "日", "src": "central:x", "in_central": True,
         "verified": {"n": 2, "agree": False}, "corrected_from": [{"form": "曰", "src": "review:a", "date": "2026-10-01"}]},     # 放行 曰、人裁 日 → 不一致
        {"id": "vol01:1:1:4", "kind": "shape", "form": "㫖", "src": "variant:zhi"},   # 码位不同、未归一 → 不一致
        {"id": "vol01:1:1:5", "kind": "shape", "form": "刋", "src": "variant:kan"},   # 归一后同字 → 一致
        {"id": "vol01:1:1:6", "kind": "shape", "form": "八", "src": "central:y"},     # 人裁通道不核
        {"id": "vol01:1:1:1", "kind": "cut", "form": "日", "src": "review:z"},
    ]) + "\n", encoding="utf-8")
    cp = tmp_path / "codepoints.yaml"
    cp.write_text("codepoints:\n  刊: 刋\n", encoding="utf-8")

    d = S.collect([tmp_path / "prod"], labels, cp)
    ry = d["groups"]["ry"]
    assert d["books"] == ["vol01"]
    assert ry["kind"] == "不同义"
    t = ry["total"]
    assert (t["occ"], t["admit"], t["review"], t["flow"], t["pick"]) == (3, 2, 1, 2, 1)
    assert (t["checked"], t["mismatch"]) == (1, 1)
    assert ry["mismatch"] == [{"id": "vol01:1:1:3", "admit": "曰", "label": "日", "channel": "dual", "drift": False}]
    assert ry["labels"] == {"shape": 1, "central": 1, "multi": 1, "corrected": 1, "cut": 1}
    assert d["groups"]["zhi"]["total"]["mismatch"] == 1 and d["groups"]["zhi"]["total"]["drift"] == 0
    assert d["groups"]["kan"]["total"]["checked"] == 1 and "mismatch" not in d["groups"]["kan"]["total"]

    pj, pm = S.run([tmp_path / "prod"], tmp_path / "out", labels, cp, tag="t", date="2026-10-24")
    assert pj.name == "2026-10-24-t.json" and json.loads(pj.read_text(encoding="utf-8"))["tag"] == "t"
    assert "| ry | 日曰 | 不同义 | 3 | 66.7% | 1 | 2 | 50.0% | 1 | 1（0） |" in pm.read_text(encoding="utf-8")


def test_review_breakdown_classifies_and_diffs(tmp_path):
    from open_guji_cv.eval import group_status as S
    from open_guji_cv.eval import review_breakdown as RB

    edges = {"䘮": {"喪"}, "喪": {"䘮"}}
    grp = {"group": {"id": "ry", "pick": None}}
    for root, extra in (("old", [{"id": "vol01:1:1:9", "char": "曰", "admit": False, "evidence": grp}]), ("new", [])):
        _page(tmp_path, root, "vol01", [
            {"id": "vol01:1:1:1", "char": "日", "admit": True, "channel": "match_ref", "evidence": {}},
            {"id": "vol01:1:1:2", "char": "曰", "admit": False, "evidence": grp},                       # G
            {"id": "vol01:1:1:3", "char": None, "admit": False, "doubts": ["occluded"], "evidence": {}},  # O 印章
            {"id": "vol01:1:1:4", "char": None, "admit": False, "evidence": {}},                         # V 䘮/喪
            {"id": "vol01:1:1:5", "char": None, "admit": False, "evidence": {"guard": "conflict"}},      # N
        ] + extra)
        for step, body in (("glyph_match", {"columns": [{"chars": [{"id": "vol01:1:1:4", "candidates": [["喪", 0.9]]},
                                                                    {"id": "vol01:1:1:5", "candidates": [["千", 0.8], ["子", 0.79]]}]}]}),
                           ("align_ref", {"chars": [{"id": "vol01:1:1:4", "align_char": "䘮"}], "coord": [{"id": "vol01:1:1:5", "ref_char": "于"}]})):
            p = tmp_path / root / "vol01" / step
            p.mkdir(parents=True, exist_ok=True)
            (p / "p0001.json").write_text(json.dumps({step: body}, ensure_ascii=False), encoding="utf-8")

    d = RB.collect([tmp_path / "new"], edges)
    assert d["books"]["vol01"] == {"cells": 5, "admit": 1, "review": 4, "G": 1, "O": 1, "V": 1, "N": 1}
    assert d["keys"]["V"] == {"䘮/喪": 1} and d["keys"]["N"] == {"于/千/子": 1} and d["keys"]["O"] == {"印章遮挡": 1}

    po, _ = S.run([tmp_path / "old"], tmp_path / "out", tag="old", date="2026-10-24")
    _, pm = S.run([tmp_path / "new"], tmp_path / "out", tag="new", date="2026-10-25", prev=po)
    md = pm.read_text(encoding="utf-8")
    assert "| vol01 | 5 | 20.0% | 4（-1） | 1（-1） |" in md
    assert "| ry | 1（-1） |" in md
