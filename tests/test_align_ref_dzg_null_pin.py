# -*- coding: utf-8 -*-
"""row_segment 钉页 dzg:null 的页，align_ref 不做坐标对位（A22 11-04，殿本 vol56 p75–78）。"""
import json

from open_guji_cv.steps import align_ref as ar


def test_dzg_null_pinned(tmp_path, monkeypatch):
    dz = tmp_path / "daizhige"
    dz.mkdir()
    rows = [{"vol": "vol56", "page": 75, "dzg": None, "why": "错收他书页"},
            {"vol": "vol56", "page": 80, "dzg": "0001-3561h0"},
            {"vol": "vol57", "page": 3}]                     # 没写 dzg 键：不算 null 钉页
    (dz / "page_pins.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    monkeypatch.setattr(ar, "corpus_path", lambda name: tmp_path / name)
    assert ar.dzg_null_pinned("vol56", 75)
    assert not ar.dzg_null_pinned("vol56", 80)
    assert not ar.dzg_null_pinned("vol57", 3)
    assert not ar.dzg_null_pinned("vol56", 76)


def test_no_pins_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "corpus_path", lambda name: tmp_path / name)
    assert not ar.dzg_null_pinned("vol56", 75)
