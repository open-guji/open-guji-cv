# -*- coding: utf-8 -*-
"""升格候选（ops.promote，共享方案 S7 语料部分）：从对勘裁决挖形近对、异体对，对照引擎仓已有的表。自造数据。"""
from __future__ import annotations

import json

from open_guji_cv.ops.promote import mine_corpus


def _cv(pair, who, cat, i):
    return json.dumps({"id": f"evt_c_{i}", "batch": "c", "seq": i, "kind": "collate_verdict",
                       "payload": {"pair": pair, "who": who, "cat": cat, "final": pair[1] if who == "theirs" else pair[0]},
                       "target": {"key": f"vol01:1:1:{i}"}}, ensure_ascii=False)


def test_mine_corpus_lists_new_and_known(tmp_path):
    repo = tmp_path / "repo"
    (repo / "config" / "dicts").mkdir(parents=True)
    (repo / "config" / "confusable_human.json").write_text(json.dumps({"pairs": {"日曰": 1.0}}, ensure_ascii=False),
                                                          encoding="utf-8")
    (repo / "config" / "dicts" / "variants.tsv").write_text("# x\n卽\t即\n旨\t㫖\n", encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / "feedback" / "events").mkdir(parents=True)
    lines, i = [], 0
    for pair, who, cat, n in ((["日", "曰"], "theirs", "", 4), (["未", "末"], "theirs", "other", 3),
                              (["土", "士"], "theirs", "other", 2), (["旨", "㫖"], "theirs", "", 5),
                              (["即", "卽"], "ours", "variant", 2), (["內", "内"], "ours", "variant", 1),
                              (["甲", "甲"], "ours", "other", 1)):
        for _ in range(n):
            i += 1
            lines.append(_cv(pair, who, cat, i))
    (ws / "feedback" / "events" / "c.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = mine_corpus(ws, min_confusable=3, repo=repo)
    assert [(x["cv"], x["truth"], x["n"], x["known"]) for x in r["confusable"]] == [
        ("日", "曰", 4, True), ("未", "末", 3, False)]                   # 土士不够 3 次；旨㫖是已知异体，不算形近
    assert [(x["pair"], x["n"], x["needs_source"]) for x in r["variants"]] == [
        (["即", "卽"], 2, False), (["內", "内"], 1, True)]
    assert r["new"] == {"confusable": 1, "variants": 1} and r["collate_verdicts"] == 17      # 同字对（甲甲）不算
