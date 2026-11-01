"""Step3 自动配页 `pins` 档（史記文淵閣本）：按逐页钉位表直接出本册格位表，不做墨量配页。"""
import json

import pytest

from open_guji_cv.steps import row_segment_pagemap as pm


def _rec(rid, cols):
    return {"id": rid, "cols": cols}


def _col(no, start, s, zm=False):
    c = {"no": no, "runs": [{"t": "text", "start": start, "s": s}]}
    if zm:
        c["zm"] = True
    return c


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    dz = tmp_path / "daizhige"
    dz.mkdir()
    recs = [
        _rec("0243-0001", [_col(0, 0, "天地"), _col(1, -1, "玄"), _col(8, 2, "黃"), _col(9, 0, "臣某", zm=True)]),
        _rec("0243-0002", [_col(7, 0, "宇宙洪荒")]),
    ]
    (dz / "0243.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                                   encoding="utf-8")
    pins = [{"book": "04", "page": 3, "head": "0243-0001 243-1a h0"},
            {"book": "04", "page": 4, "head": "0243-0001 243-1a h1"},
            {"book": "05", "page": 2, "head": "0243-0002 243-1b h0"}]
    (tmp_path / "page_pins.jsonl").write_text("\n".join(json.dumps(p) for p in pins) + "\n", encoding="utf-8")
    import open_guji_cv.core.workspace as ws
    monkeypatch.setattr(pm, "_dz_dir", lambda: dz)
    monkeypatch.setattr(ws, "corpus_path", lambda name: tmp_path / name)
    pm._SRC_SHA.clear()
    return tmp_path


def test_build_from_pins_uses_eight_columns_and_skips_roster(corpus):
    rows = pm.build_from_pins("04", "page_pins.jsonl")
    got = {(r["page"], r["col"]): (r["slots"], r["raised"], r["dzg"]) for r in rows}
    assert got == {
        (3, 1): ([1, 2], 0, "0243-0001h0"),
        (3, 2): ([-1], 1, "0243-0001h0"),
        (4, 1): ([3], 0, "0243-0001h1"),        # no=8 → 后半叶第 1 列；no=9 职名列不写
    }
    assert [(r["page"], r["col"]) for r in pm.build_from_pins("05", "page_pins.jsonl")] == [(2, 8)]


def test_fingerprint_only_follows_own_pins(corpus):
    a = pm.fingerprint("04", "page_pins.jsonl")
    b = pm.fingerprint("05", "page_pins.jsonl")
    p = corpus / "page_pins.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + json.dumps({"book": "05", "page": 3, "head": "0243-0002 243-1b h1"}) + "\n",
                 encoding="utf-8")
    assert pm.fingerprint("04", "page_pins.jsonl") == a
    assert pm.fingerprint("05", "page_pins.jsonl") != b


def test_pins_params_need_pins_path_and_dump_only_when_on():
    from open_guji_cv.steps.row_segment import RowSegmentParams
    with pytest.raises(ValueError):
        RowSegmentParams(page_map="pins")
    on = RowSegmentParams(page_map="pins", page_map_pins="page_pins.jsonl", page_map_fingerprint="x")
    d = on.model_dump()
    assert d["page_map_pins"] == "page_pins.jsonl" and on.layout_prior == ""
    assert "page_map_pins" not in RowSegmentParams().model_dump()
    assert "page_map_pins" not in RowSegmentParams(page_map="strict").model_dump()
