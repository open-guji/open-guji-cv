# -*- coding: utf-8 -*-
"""按形区分四对复核的选样逻辑（`scripts/glyph_codepoint_review_select.py`）：
按字头分层、总数≤cap 全收／超了按比例抽、等距取样、剩余数报对。"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

BOOK = "keben"


def _tiny_patch(size: int = 64) -> bytes:
    img = np.full((size, size), 255, np.uint8)
    cv2.rectangle(img, (size // 4, size // 4), (3 * size // 4, 3 * size // 4), 0, -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def test_collect_instances_scopes_by_book_and_char(tmp_path):
    import sqlite3

    from open_guji_cv.clustering.glyph_db import GlyphDB
    import glyph_codepoint_review_select as sel

    db_path = tmp_path / "g.db"
    db = GlyphDB(db_path)
    db.admit_instance(f"{BOOK}:1:1:1", "强", _tiny_patch(), provenance="align")
    db.admit_instance(f"{BOOK}:1:1:2", "強", _tiny_patch(), provenance="align")
    db.admit_instance(f"{BOOK}:1:1:3", "却", _tiny_patch(), provenance="align")
    db.admit_instance("otherbook:1:1:1", "強", _tiny_patch(), provenance="align")

    conn = sqlite3.connect(str(db_path))
    groups = sel.collect_instances(conn, BOOK)
    assert groups["强"] == [f"{BOOK}:1:1:1"]
    assert groups["強"] == [f"{BOOK}:1:1:2"]           # otherbook 的一条不该混进来
    assert groups["却"] == [f"{BOOK}:1:1:3"]
    assert groups["卻"] == [] and groups["回"] == [] and groups["囘"] == []
    db.close()


def test_stratified_sample_under_cap_returns_everything():
    import glyph_codepoint_review_select as sel

    groups = {"强": ["a", "b"], "強": ["c"]}
    sample, leftover = sel.stratified_sample(groups, cap=40)
    assert sample == groups
    assert leftover == {"强": 0, "強": 0}


def test_stratified_sample_over_cap_is_proportional_and_total_matches_cap():
    import glyph_codepoint_review_select as sel

    groups = {"强": [f"s{i}" for i in range(80)], "強": [f"S{i}" for i in range(20)],
             "却": [f"q{i}" for i in range(4)], "卻": [f"Q{i}" for i in range(4)]}
    sample, leftover = sel.stratified_sample(groups, cap=40)
    assert sum(len(v) for v in sample.values()) == 40
    # 大组分到的名额该明显多于小组，但小组也至少分到 1 张
    assert len(sample["强"]) > len(sample["強"]) > len(sample["却"]) >= 1
    assert len(sample["卻"]) >= 1
    for c in groups:
        assert leftover[c] == len(groups[c]) - len(sample[c])
    assert sum(leftover.values()) == sum(len(v) for v in groups.values()) - 40


def test_stratified_sample_is_evenly_spaced_not_just_head():
    import glyph_codepoint_review_select as sel

    groups = {"强": [f"s{i:03d}" for i in range(100)]}
    sample, _ = sel.stratified_sample(groups, cap=10)
    picked = sample["强"]
    assert len(picked) == 10
    assert picked != [f"s{i:03d}" for i in range(10)]     # 不是掐头
    idx = [int(p[1:]) for p in picked]
    assert idx == sorted(idx)
    assert idx[-1] - idx[0] > 50                          # 铺开了，不是挤在一段


def test_empty_groups_are_handled():
    import glyph_codepoint_review_select as sel

    sample, leftover = sel.stratified_sample({"强": [], "強": []}, cap=40)
    assert sample == {"强": [], "強": []}
    assert leftover == {"强": 0, "強": 0}


def test_to_card_labels_pair_correctly():
    import glyph_codepoint_review_select as sel

    png = _tiny_patch()
    card = sel.to_card("bxgb:11:5:18", "囘", png)
    assert card["pair"] == "回囘"
    assert card["char"] == "囘"
    assert card["instance_id"] == "bxgb:11:5:18"
    import base64
    assert base64.b64decode(card["patch_png_b64"]) == png
