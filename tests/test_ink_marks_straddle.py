# -*- coding: utf-8 -*-
"""朱楓林集（MBJ）三条按书开的切字规则（CV2 2026-11-28）：藏书印／墨点格旗（cell_shrink `ink_marks`）＋判非字（seed_admit `ink_marks`）、
骑线字合一格（row_segment `straddle_merge`）。自造数据。"""
from __future__ import annotations

import numpy as np
import pytest

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_align_ref, page_match, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars, PageChars
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.cell_shrink import CellShrinkParams, InkMarkParams, ink_mark_flags
from open_guji_cv.steps.row_segment import RowSegmentParams, StraddleMergeParams, _apply_straddle, straddle_pairs
from open_guji_cv.steps.seed_admit import SeedAdmitParams

# ── 格旗判据 ──────────────────────────────────────────────────────────────
P = InkMarkParams()


def test_seal_solid_and_framed():
    solid = np.ones((140, 220), np.uint8)
    assert ink_mark_flags(solid, 220, 140, 103, P) == ["ink_seal"]
    framed = np.zeros((150, 150), np.uint8)
    for i in range(20):                       # 20 个碎块（框线印的印文）
        framed[10 + 6 * i:12 + 6 * i, 20:24] = 1
    assert ink_mark_flags(framed, 150, 150, 103, P) == ["ink_seal"]
    assert ink_mark_flags(solid, 220, 140, None, P) == []          # 没有参考字宽：宽度一支不判


def test_speck_and_flat_one():
    dot = np.zeros((40, 40), np.uint8)
    dot[10:30, 10:30] = 1                      # 400px 墨点
    assert ink_mark_flags(dot, 40, 40, 103, P) == ["ink_speck"]
    one = np.zeros((20, 90), np.uint8)
    one[8:14, :] = 1                           # 扁的「一」：宽高比 4.5，不中
    assert ink_mark_flags(one, 90, 20, 103, P) == []
    char = np.zeros((100, 100), np.uint8)
    char[10:90, 45:55] = 1
    char[45:55, 10:90] = 1
    assert ink_mark_flags(char, 100, 100, 103, P) == []


def test_params_off_not_in_dump():
    assert "ink_marks" not in CellShrinkParams().model_dump()
    assert "straddle_merge" not in RowSegmentParams().model_dump()
    assert "ink_marks" not in SeedAdmitParams().model_dump()
    assert CellShrinkParams(ink_marks={}).model_dump()["ink_marks"]["seal_w"] == 1.6
    assert RowSegmentParams(straddle_merge={}).model_dump()["straddle_merge"]["band_min"] == 0.28


# ── 骑线字 ────────────────────────────────────────────────────────────────
W, H, PER_, RW_ = 600, 400, 100.0, 140.0


def _cell(slot, x_l, x_r, y0, kind="char"):
    """右上原点的格：x_l／x_r 是左上原点的左右边。"""
    xr0, xr1 = W - 1 - x_r, W - 1 - x_l
    return CellRec(slot=slot, pos=slot, y0=y0, y1=y0 + PER_, x0=0, x1=RW_, kind=kind, order=slot,
                   quad_page=[[xr1, y0], [xr0, y0], [xr0, y0 + PER_], [xr1, y0 + PER_]])


def _page_cells():
    # 右列（列 1）x 300–440，左列（列 2）x 160–300，界行在 x=300
    c1 = ColumnCells(col=1, ok=True, n_body_slots=3, period=PER_, content_x=(0, RW_), cells=[_cell(s, 300, 440, 100 * (s - 1)) for s in (1, 2, 3)])
    c2 = ColumnCells(col=2, ok=True, n_body_slots=3, period=PER_, content_x=(0, RW_), cells=[_cell(s, 160, 300, 100 * (s - 1)) for s in (1, 2, 3)])
    return PageCells(page=1, period=PER_, ref_w=RW_, columns=[c1, c2])


def _page_img():
    g = np.full((H, W), 255, np.uint8)
    g[0:100, 299:302] = 0
    g[200:300, 299:302] = 0                    # 界行在第 2 格处断开
    g[110:190, 250:350:2] = 0                  # 骑线字：竖笔排满界行两侧
    g[20:80, 330:420] = 0                    # 第 1、3 格两侧是正常字，离界行有空白
    g[20:80, 180:270] = 0
    g[220:280, 330:420] = 0
    g[220:280, 180:270] = 0
    return g


def test_straddle_pairs_and_apply():
    pc = _page_cells()
    pairs = straddle_pairs(_page_img(), pc, StraddleMergeParams())
    assert pairs == [(1, 2, 2, 2)]
    out = _apply_straddle(pc, pairs)
    r = next(c for c in out.columns[0].cells if c.slot == 2)
    lft = next(c for c in out.columns[1].cells if c.slot == 2)
    assert r.kind == "char" and r.flags == ["straddle:2:2"]
    assert lft.kind == "blank" and lft.flags == ["straddle_into:1:2"]
    assert _apply_straddle(pc, []) is pc


# ── seed_admit 判非字 ─────────────────────────────────────────────────────
BOOK, PAGE, COL = "tbook", 1, 1


def _box(slot, flags=()):
    return CharRec(id=f"{BOOK}:{PAGE}:{COL}:{slot}", slot=slot, pos=slot, idx=slot - 1, cell_type="char",
                   bbox_col=(0, 100 * (slot - 1), 90, 100 * slot - 10), bbox_page=(0, 100 * (slot - 1), 90, 100 * slot - 10),
                   height=90, width=90, flags=list(flags))


def _run(tmp_path, monkeypatch, params, boxes, ref_slots):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    monkeypatch.setattr(lookup, "human_chars", lambda book, log=None, stale=None, bind=None, lost=None: {})
    ctx = RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache),
                     params={"seed_admit": params}, log=lambda s: None)
    chars = {1: "山", 2: "水", 3: "木", 4: "火"}
    recs = [dict(slot=s, verdict="same", cov=1.0, wmax=0.0, char=c, candidates=[(c, 1.0)]) for s, c in chars.items()]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=s, align_char=chars[s]) for s in ref_slots], col=COL))
    write_product(ctx, "cell_shrink", PAGE, char_index=PageChars(page=PAGE, columns=[
        ColumnChars(col=COL, ok=True, n_instances=len(boxes), chars=boxes)]))
    page = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in page.columns for r in cc.chars}


def _dot(slot):
    """孤立墨点：小框落在格中间，离上下字都远。"""
    y = 100 * (slot - 1) + 35
    return _box(slot, ["ink_speck"]).model_copy(update={"bbox_page": (35, y, 55, y + 20), "width": 20, "height": 20})


BOXES = [_box(1), _box(2, ["ink_seal"]), _dot(3), _dot(4)]


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_seed_admit_ink_marks(tmp_path, monkeypatch):
    off = _run(tmp_path / "a", monkeypatch, SeedAdmitParams(), BOXES, ref_slots=[1, 4])
    assert all(r.admit for r in off.values())
    on = _run(tmp_path / "b", monkeypatch, SeedAdmitParams(ink_marks=True), BOXES, ref_slots=[1, 4])
    assert on[1].admit and on[1].char == "山"
    assert on[2].admit and on[2].char is None and on[2].channel == "seal" and on[2].evidence["lane"]["via"] == "ink_seal"
    assert on[3].admit and on[3].char is None and on[3].channel == "blank_ink" and on[3].evidence["lane"]["nonchar"]
    assert not on[4].admit and "seg_defect" in on[4].doubts and on[4].evidence["demoted_from"]["by"] == "ink_marks"


def test_straddle_patch_whole_char():
    from open_guji_cv.steps.cell_shrink import straddle_patch

    class _Ctx:
        def raw_page(self, page):
            return _page_img()

    pc = _apply_straddle(_page_cells(), [(1, 2, 2, 2)])
    patch, box = straddle_patch(_Ctx(), 1, pc, 1, 2, 0.08)
    xr0, y0, xr1, y1 = box                      # 右上原点
    assert W - 1 - xr1 <= 250 and W - 1 - xr0 >= 348     # 左右两半都在
    assert 100 < y0 <= 110 and 190 <= y1 < 200
    assert (patch < 128).sum() == ((_page_img()[110:190, 250:350]) < 128).sum()   # 界行、邻格的字不进来
    assert straddle_patch(_Ctx(), 1, pc, 1, 1, 0.08) is None


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_speck_touching_char_is_half(tmp_path, monkeypatch):
    """墨点贴着同列下一字（切坏的半字，朱楓林集 53:5:8「夫」上一竖）：对位无字也不判非字，送审。"""
    half = _box(3, ["ink_speck"])
    half = half.model_copy(update={"bbox_page": (20, 260, 40, 295), "width": 20, "height": 35})
    on = _run(tmp_path, monkeypatch, SeedAdmitParams(ink_marks=True), [_box(1), _box(2), half, _box(4)], ref_slots=[1, 2, 4])
    assert not on[3].admit and "seg_defect" in on[3].doubts and on[3].evidence["speck_half"]


def test_straddle_skips_narrow_bands():
    """列窗认错（一列劈成两窄列）时不认骑线。"""
    pc = _page_cells()
    narrow = pc.model_copy(update={"columns": [pc.columns[0].model_copy(update={"content_x": (0, 0.6 * RW_)}), pc.columns[1]]})
    assert straddle_pairs(_page_img(), narrow, StraddleMergeParams()) == []
