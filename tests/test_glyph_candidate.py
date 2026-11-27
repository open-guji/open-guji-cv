"""3c `glyph_candidate`（2026-11-27）：排序＋异体族展开（纯函数）、并入收尾 evidence.c、骨架里的位置。全部自造数据。"""
from __future__ import annotations

import numpy as np

from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.products.kinds.read import CandRec
from open_guji_cv.steps.glyph_analyzer import merge_cell
from open_guji_cv.steps.glyph_candidate import GlyphCandidateParams, rank_cell

from helpers import page_match

CHARS = list("甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥")
INDEX = {c: i for i, c in enumerate(CHARS)}


def _sims(**kw):
    s = np.full(len(CHARS), 0.1, np.float32)
    for c, v in kw.items():
        s[INDEX[c]] = v
    return s


def test_rank_plain_top_k_descending():
    s = _sims(丙=0.9, 甲=0.8, 乙=0.7)
    cands, fam_of = rank_cell(s, CHARS, INDEX, lambda c: [], topk=3, fam_top=0)
    assert [c for c, _ in cands] == ["丙", "甲", "乙"] and fam_of == {}
    assert cands[0][1] == 0.9


def test_rank_family_members_inserted_after_head_by_own_similarity():
    s = _sims(丙=0.9, 甲=0.8, 乙=0.7, 丁=0.6, 戊=0.5, 子=0.55, 丑=0.52)
    fam = {"丙": ["子", "丑", "丙"], "乙": ["丑"]}
    cands, fam_of = rank_cell(s, CHARS, INDEX, lambda c: fam.get(c, []), topk=8, fam_top=3, fam_after=3)
    got = [c for c, _ in cands]
    assert got[:3] == ["丙", "甲", "乙"]                     # 头 3 个原样
    assert got[3:5] == ["子", "丑"]                          # 族员接着，按自己的图像分降序
    assert got[5:7] == ["丁", "戊"]                          # 然后才是其余图像名次
    assert fam_of == {"子": "丙", "丑": "丙"}                # 丑 先由丙带进来，记第一个头名
    assert len(got) == 8


def test_rank_family_member_outside_table_is_skipped():
    s = _sims(丙=0.9)
    cands, _ = rank_cell(s, CHARS, INDEX, lambda c: ["𠀀"], topk=5, fam_top=1, fam_after=1)
    assert "𠀀" not in [c for c, _ in cands]


def test_merge_cell_adds_c_evidence_and_new_candidates_after_3a():
    r = merge_cell(page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": [("甲", 0.9)]}]).columns[0].chars[0],
                   None, {}, 5, "elastic",
                   CandRec(id="tbook:1:1:1", slot=1, cands=[["甲", 0.8], ["乙", 0.7], ["子", 0.6]], fam_of={"子": "乙"}))
    assert [c.char for c in r.cands] == ["甲", "乙", "子"]
    assert r.cands[0].evidence["a"]["sim"] == 0.9 and r.cands[0].evidence["c"] == {"sim": 0.8}
    assert r.cands[2].evidence["c"] == {"sim": 0.6, "fam_of": "乙"} and "a" not in r.cands[2].evidence
    assert all(c.p is None for c in r.cands)


def test_merge_cell_ignores_cand_rec_that_did_not_run():
    r = merge_cell(page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": [("甲", 0.9)]}]).columns[0].chars[0],
                   None, {}, 5, "elastic", CandRec(id="x", slot=1, ran=False))
    assert [c.char for c in r.cands] == ["甲"] and "c" not in r.cands[0].evidence


def test_default_off_and_in_read_stage_before_final():
    assert GlyphCandidateParams().enabled is False
    pl = load_pipeline("keben_body_v2")
    read = pl.stages["read"]
    assert read.index("glyph_candidate") < read.index("glyph_analyzer") and read[-1] == "glyph_analyzer"
