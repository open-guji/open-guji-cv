# -*- coding: utf-8 -*-
"""pair_form：放行字按第 5 步 5a.3 的字形证据改成刻形（缺省关）。数据自造。"""
import json
from types import SimpleNamespace

from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _pair_form_pass

B = "tbook:1"


def _row(pair="淸清", char="淸", tier=3, p=0.99, cand="淸", rank=1):
    return {"pair": pair, "tier": tier, "p": p, "lean": char, "char": char, "cand": cand, "rank": rank}


def _run(cells, table="-", canon=None):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=int(s), admit=c.get("admit", True), char=c.get("char"), doubts=[], channel=c.get("channel", "match_ref"),
                     provenance=c.get("provenance", "match"), evidence={}) for s, c in cells.items()]
    mmap = {f"{B}:1:{s}": SimpleNamespace(stage={"pair": c["rows"]} if c.get("rows") is not None else None) for s, c in cells.items()}
    ctx = SimpleNamespace(book=SimpleNamespace(codepoints=bool(canon), canonical_char=canon)) if canon else None
    n = _pair_form_pass(SeedAdmitParams(db_path="x", pair_form=table), [ColumnAdmit(col=1, chars=recs)], mmap, ctx)
    return n, {r.id.split(":")[-1]: r for r in recs}


def test_changes_released_char_to_carved_form_keeping_channel():
    n, r = _run({"1": {"char": "清", "rows": [_row()]}})
    assert n == 1 and r["1"].char == "淸" and (r["1"].channel, r["1"].provenance, r["1"].admit) == ("match_ref", "match", True)
    assert r["1"].evidence["pair_form"] == {"from": "清", "to": "淸", "pair": "淸清", "tier": 3, "p": 0.99, "rank": 1}


def test_leaves_alone():
    row = _row()
    assert _run({"1": {"char": "淸", "rows": [row]}})[0] == 0                                   # 已是刻形
    assert _run({"1": {"char": "清", "rows": [_row(char=None)]}})[0] == 0                       # 没过门槛：证据无 char
    assert _run({"1": {"char": "清", "rows": []}})[0] == 0 and _run({"1": {"char": "清", "rows": None}})[0] == 0
    assert _run({"1": {"char": "清", "admit": False, "rows": [row]}})[0] == 0                   # 没放行
    assert _run({"1": {"char": "清", "channel": "human", "provenance": "human", "rows": [row]}})[0] == 0   # 人裁
    assert _run({"1": {"char": "青", "rows": [row]}})[0] == 0                                   # 放行字不在这一对里
    assert _run({"1": {"char": "清", "rows": [_row(pair="淸清", char="水")]}})[0] == 0           # 给的字不在这一对里
    two = [_row(), _row(pair="清青", char="青", cand="青", rank=2)]                              # 含放行字的两对给了不同的字
    assert _run({"1": {"char": "清", "rows": two}})[0] == 0


def test_attribution_table_and_codepoint_canon(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("schema: pair_attribution/1\npairs:\n  淸清: {attr: context}\n  簡𥳑: {attr: shape, variant: true}\n  壞壤: {attr: shape}\n", encoding="utf-8")
    assert _run({"1": {"char": "清", "rows": [_row()]}}, table=str(f))[0] == 0                  # 归文意：不按字形改
    canon = {"簡": "𥳑"}.get
    assert _run({"1": {"char": "𥳑", "rows": [_row(pair="簡𥳑", char="簡")]}}, canon=lambda c: canon(c, c))[0] == 0   # 册码位表把 簡 归走
    assert _run({"1": {"char": "𥳑", "rows": [_row(pair="簡𥳑", char="簡")]}}, table=str(f))[0] == 1
    n, r = _run({"1": {"char": "壤", "rows": [_row(pair="壞壤", char="壞", cand="壞")]}}, table=str(f))   # 异字对：只记证据，不改字
    assert n == 0 and r["1"].char == "壤" and r["1"].evidence["pair_form_review"]["to"] == "壞"


def test_off_by_default_and_not_in_dump():
    d = SeedAdmitParams(db_path="x").model_dump()
    assert "pair_form" not in d and "pair_form_fingerprint" not in d
    assert SeedAdmitParams(db_path="x", pair_form="-").pair_form_fingerprint == "all-shape"
    assert json.dumps(SeedAdmitParams(db_path="x", pair_form="-").model_dump(), default=str) != json.dumps(d, default=str)
