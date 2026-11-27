# -*- coding: utf-8 -*-
"""字框几何闸（`seed_admit.seg_box_check`，CV2 2026-11-27，朱楓林集 MBJ 报）：碎格、框线扁条、墨点、一字劈两框、过高框送审。自造数据。"""
from __future__ import annotations

import pytest

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars, PageChars
from open_guji_cv.products.kinds.gate import GateManifest
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams
from open_guji_cv.steps.seed_admit_lanes import seg_box_defects

pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")

BOOK, PAGE, COL, PER, RW = "tbook", 1, 1, 100.0, 100.0


def _box(slot, y0, h, w=90.0, sub=None):
    return CharRec(id=f"{BOOK}:{PAGE}:{COL}:{slot}{sub or ''}", slot=slot, pos=slot, idx=slot - 1, sub=sub, cell_type="char",
                   bbox_col=(0, y0, w, y0 + h), bbox_page=(0, y0, w, y0 + h), height=h, width=w)


def _col(boxes):
    return PageChars(page=PAGE, columns=[ColumnChars(col=COL, ok=True, n_instances=len(boxes), chars=boxes)])


def test_kinds():
    boxes = [_box(1, 0, 90),            # 正常
             _box(2, 100, 8, w=95),     # 框线扁条
             _box(3, 200, 15, w=15),    # 墨点
             _box(4, 300, 45, w=70), _box(5, 350, 45, w=70),   # 一字劈两框（合起来 0.95 格）
             _box(6, 500, 180),         # 过高
             _box(7, 700, 85)]
    got = seg_box_defects(_col(boxes).columns, PER, RW)
    k = {int(i.rsplit(":", 1)[1]): v for i, v in got.items()}
    assert k[2] == ["frame_line"] and k[3][0] == "speck" and "split_pair" in k[4] and "split_pair" in k[5]
    assert k[6] == ["tall"] and 1 not in k and 7 not in k


def test_small_note_only_tall_and_no_period():
    boxes = [_box(1, 0, 40, w=40, sub="a"), _box(1, 0, 170, w=40, sub="b")]
    got = seg_box_defects(_col(boxes).columns, PER, RW)
    assert list(got.values()) == [["tall"]]
    assert seg_box_defects(_col(boxes).columns, None, RW) == {}


def _run(tmp_path, monkeypatch, params, boxes):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    monkeypatch.setattr(lookup, "human_chars", lambda book, log=None, stale=None, bind=None, lost=None: {})
    ctx = RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params}, log=lambda s: None)
    chars = ["山", "水", "木"]
    recs = [dict(slot=i + 1, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)]) for i, c in enumerate(chars)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=i + 1, align_char=c) for i, c in enumerate(chars)], col=COL))
    write_product(ctx, "cell_shrink", PAGE, char_index=_col(boxes))
    write_product(ctx, "cut_gate", PAGE, gate_manifest=GateManifest(
        page=PAGE, admitted=True, period=PER, ref_w=RW, column_widths=[RW], median_width=RW, columns=[]))
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in page.columns for r in cc.chars}


BOXES = [_box(1, 0, 90), _box(2, 100, 8, w=95), _box(3, 200, 90)]


def test_off_by_default(tmp_path, monkeypatch):
    p = SeedAdmitParams()
    assert "seg_box_check" not in p.model_dump()
    r = _run(tmp_path, monkeypatch, p, BOXES)
    assert all(x.admit for x in r.values())


def test_on_demotes_to_seg_defect(tmp_path, monkeypatch):
    p = SeedAdmitParams(seg_box_check=["all"])
    assert p.model_dump()["seg_box_check"] == ["sliver", "frame_line", "speck", "split_pair", "tall"]
    r = _run(tmp_path, monkeypatch, p, BOXES)
    x = r[2]
    assert not x.admit and "seg_defect" in x.doubts
    assert x.evidence["seg_box"] == ["frame_line"] and x.evidence["seg_kind"] == "frame_residue"
    assert x.evidence["demoted_from"]["by"] == "seg_box_check"
    assert r[1].admit and r[3].admit


def test_pick_criteria(tmp_path, monkeypatch):
    assert SeedAdmitParams(seg_box_check=True).seg_box_check == SeedAdmitParams(seg_box_check="all").seg_box_check
    with pytest.raises(ValueError):
        SeedAdmitParams(seg_box_check=["oops"])
    r = _run(tmp_path, monkeypatch, SeedAdmitParams(seg_box_check=["tall", "split_pair"]), BOXES)
    assert all(x.admit for x in r.values())          # 没开 frame_line：扁条不拦（殿本「一」本来就扁）
