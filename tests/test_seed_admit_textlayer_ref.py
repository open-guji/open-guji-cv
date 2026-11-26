# -*- coding: utf-8 -*-
"""textlayer_ref_gap：整理本没字的待审格取图源文本层字（缺省关）。直接测 `_textlayer_ref_gap_pass`，数据自造。"""
from __future__ import annotations

import gzip
import json
from types import SimpleNamespace as NS

from open_guji_cv.groups import textlayer_ref as tl
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _textlayer_ref_gap_pass

B = "vol01"
TEXT = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏"          # 26 字


def _layer(tmp_path, text=TEXT, page_chars=None):
    """文本层：字框是格框的 1.4 倍缩放＋x 镜像（模拟重切图的另一套坐标系）。格框 (x0,y0,x1,y1)：第 i 字在 (10*i, 5*(i%4), 10*i+9, 5*(i%4)+9)。"""
    d = tmp_path / "tl"
    (d / "7").mkdir(parents=True, exist_ok=True)
    tl._pagemap.cache_clear(); tl._chapter.cache_clear()
    (d / "pagemap.json").write_text(json.dumps({B: [{"our": 1, "their": [7, 40]}, {"our": 2, "n": 0, "status": "no_text"}]}))
    pc = page_chars or text
    r = {"p": 40, "c": pc, "x": [1000 - 1.4 * (10 * i + 9) for i in range(len(pc))], "y": [1.4 * 5 * (i % 4) for i in range(len(pc))],
         "w": [12.6] * len(pc), "hgt": [12.6] * len(pc)}
    with gzip.open(d / "7" / "text.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(d)


def _run(tmp_path, miss, cands=None, coord=None, mod=None, page_chars=None, **params):
    d = _layer(tmp_path, page_chars=page_chars)
    p = SeedAdmitParams(db_path="x", textlayer_ref_gap=d, **params)
    recs, boxes = [], []
    for i, ch in enumerate(TEXT):
        s = i + 1
        c = {"char": "一" if i in miss else ch, "admit": i not in miss}
        if mod and i in mod:
            c.update(mod[i])
        recs.append(AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c["admit"], char=c["char"], doubts=list(c.get("doubts", [])),
                             channel=c.get("channel"), provenance=c.get("provenance", ""), evidence=c.get("evidence") or {}))
        boxes.append(NS(id=f"{B}:1:{s}", bbox_page=(10 * i, 5 * (i % 4), 10 * i + 9, 5 * (i % 4) + 9)))
    ctx = NS(book=NS(id=B), product=lambda kind, page: NS(columns=[NS(chars=boxes)], alt_columns=[]))
    mm = {f"{B}:1:{s}": NS(candidates=v) for s, v in (cands or {}).items()}
    co = {r.id: TEXT[r.slot - 1] for r in recs if r.slot - 1 not in miss}
    co.update({f"{B}:1:{s}": v for s, v in (coord or {}).items()})
    n = _textlayer_ref_gap_pass(p, [ColumnAdmit(col=1, chars=recs)], mm, co, ctx, 1)
    return n, {r.slot: r for r in recs}


def test_admits_text_layer_char_on_ref_gap(tmp_path):
    n, r = _run(tmp_path, {4, 9})
    assert n == 2 and r[5].admit and r[5].char == "宇" and r[10].char == "月"
    assert (r[5].channel, r[5].provenance) == ("textlayer_ref", "align")
    assert r[5].evidence["lane"]["lane"] == "textlayer_ref" and r[5].doubts == ["lane_textlayer_ref"]


def test_leaves_alone(tmp_path):
    n, r = _run(tmp_path, {1, 4, 5, 6, 7, 8}, coord={5: "宙"},
                mod={1: {"provenance": "human", "channel": "human"}, 4: {"doubts": ["occluded"]},
                     5: {"evidence": {"occluded": {"via": "coord"}}}, 6: {"doubts": ["excluded"]}}, textlayer_ref_page_min=0.5, textlayer_ref_min_pairs=12)
    # slot2 人裁；slot5 遮挡；slot6 遮挡证据（且对位有字）；slot7 排除；slot8、9 正常缺字 → 放这两格
    assert not any(r[k].admit and r[k].channel == "textlayer_ref" for k in (2, 5, 6, 7))
    assert n == 2 and r[8].char == TEXT[7] and r[9].char == TEXT[8]


def test_pua_abstains_unless_allowed(tmp_path):
    pc = TEXT[:4] + "" + TEXT[5:]
    assert _run(tmp_path, {4}, page_chars=pc)[0] == 0
    n, r = _run(tmp_path, {4}, page_chars=pc, textlayer_ref_allow_pua=True)
    assert n == 1 and r[5].char == ""


def test_near_form_guard(tmp_path):
    # 库候选里有与文本层字（宇）成人裁形近对的字时留审：造 日/曰 对用库里实际有的对
    pairs = [tuple(k) for k in json.loads(open("config/confusable_human.json", encoding="utf-8").read())["pairs"] if len(k) == 2]
    a, b = pairs[0]
    pc = TEXT[:4] + a + TEXT[5:]
    assert _run(tmp_path, {4}, page_chars=pc, cands={5: [(b, 0.9)]})[0] == 0
    assert _run(tmp_path, {4}, page_chars=pc, cands={5: [(b, 0.9)]}, textlayer_ref_near_guard=False)[0] == 1


def test_page_without_text_layer_or_poor_match_abstains(tmp_path):
    assert _run(tmp_path, {4}, page_chars="甲乙丙丁" * 6)[0] == 0           # 页相似度太低／配对不足


def test_off_by_default_and_not_in_dump():
    d = SeedAdmitParams(db_path="x").model_dump()
    assert not any(k.startswith("textlayer_ref") for k in d)


def test_fingerprint_follows_data(tmp_path):
    d = _layer(tmp_path)
    f1 = tl.fingerprint(d)
    (tmp_path / "tl" / "7" / "text.jsonl.gz").write_bytes(b"x")
    assert tl.fingerprint(d) != f1 and tl.fingerprint(str(tmp_path / "none")).endswith("missing")
    assert SeedAdmitParams(db_path="x", textlayer_ref_gap=d).model_dump()["textlayer_ref_gap_fingerprint"] == tl.fingerprint(d)
