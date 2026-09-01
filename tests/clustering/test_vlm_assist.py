"""vlm_assist 单测：识别语法解析与导入契约。"""

import json

from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.clustering.vlm_assist import (import_recognitions,
                                                make_sheets, parse_spec)


def test_parse_spec():
    assert parse_spec("一") == [("一", 0.9, False)]
    assert parse_spec("日|曰") == [("日", 0.6, False), ("曰", 0.3, False)]
    assert parse_spec("檢~") == [("檢", 0.55, True)]
    assert parse_spec("卯|夘~") == [("卯", 0.5, True), ("夘", 0.3, True)]
    assert parse_spec(None) == []
    assert parse_spec("") == []


def test_sheets_and_import_roundtrip(synth_book, tmp_path):
    sheets = tmp_path / "sheets"
    mapping = make_sheets(synth_book, sheets, min_size=2)
    assert mapping, "合成书应有 size>=2 的簇"
    assert (sheets / "batch_01.png").exists()

    # 给第一批前两个簇写识别结果
    b1 = mapping["batch_01"]
    recs = {"batch_01": {"1": "甲", "2": "乙|丙~"}}
    (sheets / "recognitions.json").write_text(
        json.dumps(recs, ensure_ascii=False), encoding="utf-8")
    stats = import_recognitions(synth_book, sheets, VariantMap({}))
    assert stats["recognized"] == 2

    cands = json.load(open(synth_book / "phase6_labels" / "candidates.json",
                           encoding="utf-8"))
    assert cands["sources"] == ["vlm"]
    by_cid = {c["cluster_id"]: c for c in cands["clusters"]}
    c1 = by_cid[b1["1"]["cluster"]]
    assert c1["candidates"][0]["char"] == "甲"
    assert c1["candidates"][0]["p"] == 0.9
    c2 = by_cid[b1["2"]["cluster"]]
    assert [x["char"] for x in c2["candidates"]] == ["乙", "丙"]
    assert all(x["surface_uncertain"] for x in c2["candidates"])
