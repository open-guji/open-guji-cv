# -*- coding: utf-8 -*-
"""印章／大片污损遮挡（`occluded`，overview#195）。

用户 09-28：vol03 p3 那一块「太脏，全都不能入库」，人审默认用整理本的字，文本照常输出。
钉住：检测（成块才算、补洞、孤立脏格不算）→ Step7 一律不放行、默认字取坐标对位 →
空格位假格当非字 → 关掉开关退回原行为 → 文本层照出默认字。
"""
from __future__ import annotations

import numpy as np

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.recog import (AdmitRec, ColumnMatch, CoordRec, MatchRec,
                                               PageAlignRef, PageMatch)
from open_guji_cv.report.slots import _to_slot
from open_guji_cv.steps.occlusion import cell_densities, occluded_cells
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE = "tbook", 1
NCOL, NROW, CW, CH = 9, 21, 100, 100
SEAL = {(c, s) for c in (2, 3, 4, 5) for s in range(2, 9)}   # 印章压住的格
HOLE = (3, 5)                                                 # 印章中间一格墨点被字挡住，自己不热


def _page_and_cells():
    rng = np.random.default_rng(195)
    img = np.full((NROW * CH + 200, NCOL * CW + 200), 255, np.uint8)
    cols = []
    for c in range(1, NCOL + 1):
        x0 = 100 + (NCOL - c) * CW          # 右起第一列
        cells = []
        for s in range(1, NROW + 1):
            y0 = 100 + (s - 1) * CH
            if (c, s) in SEAL and (c, s) != HOLE:
                for _ in range(10):             # 中等墨点（3x3 = 9px）撒在格里
                    x, y = rng.integers(x0 + 5, x0 + CW - 8), rng.integers(y0 + 5, y0 + CH - 8)
                    img[y:y + 3, x:x + 3] = 0
            cells.append(CellRec(slot=s, pos=s, y0=y0 - 100, y1=y0, x0=0, x1=CW, kind="char",
                                 order=s, quad_page=[(x0 + CW, y0), (x0, y0), (x0, y0 + CH),
                                                     (x0 + CW, y0 + CH)]))
        cols.append(ColumnCells(col=c, ok=True, n_body_slots=NROW, period=float(CH),
                                border_top=0.0, cells=cells))
    # 正常页也有的孤立脏格：版框角上一格墨点多，不成块
    img[100 + 20 * CH + 10: 100 + 20 * CH + 40: 6, 100 + 10: 100 + 60: 6] = 0
    return img, PageCells(page=PAGE, period=float(CH), ref_w=float(CW), columns=cols)


def test_detects_block_fills_hole_and_ignores_isolated_dirty_cell():
    img, cells = _page_and_cells()
    hit = occluded_cells(cell_densities(img, cells))
    got = {(c, s) for c, s, _sub in hit}
    assert SEAL <= got, f"印章格漏检：{sorted(SEAL - got)}"
    assert HOLE in got, "块内被字挡住的格要补进来"
    assert (NCOL, NROW) not in got, "孤立的脏格成不了块，不该算遮挡"
    # 扩半格的密度会把紧挨印章的一圈也带进来，但不许漫到远处
    assert all(1 <= c <= 6 and 1 <= s <= 9 for c, s in got), sorted(got)


def test_clean_page_has_no_occlusion():
    img = np.full((NROW * CH + 200, NCOL * CW + 200), 255, np.uint8)
    _img, cells = _page_and_cells()
    assert occluded_cells(cell_densities(img, cells)) == {}


# ── Step7 ────────────────────────────────────────────────────────────────
def _run_seed(tmp_path, monkeypatch, *, params=None, coord=None):
    img, cells = _page_and_cells()
    ctx = make_ctx(tmp_path, make_book(BOOK), raw={PAGE: img}, monkeypatch=monkeypatch)
    if params is not None:
        ctx = RunContext(ctx.book, ctx.store, ctx.cache, params={"seed_admit": params},
                         log=lambda s: None)
        ctx._raw[PAGE] = img
    # 列 3：slot 3 在印章里（库 same 0.999，平时 match_solo 直接放行）；slot 2 是印章切出的假格；
    # slot 15 在印章外，照常放行。
    recs = [MatchRec(id=f"{BOOK}:{PAGE}:3:{s}", slot=s, verdict="same", char="衡", cov=0.999,
                     candidates=[("衡", 0.999)]) for s in (2, 3, 15)]
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=PageMatch(page=PAGE, columns=[ColumnMatch(col=3, ok=True, chars=recs)]))
    write_product(ctx, "context_decide", PAGE,
                  context_decision=page_decision(PAGE, BOOK, recs=[], col=3))
    write_product(ctx, "row_segment", PAGE, cells=cells)
    coord = coord if coord is not None else [
        CoordRec(id=f"{BOOK}:{PAGE}:3:2", col=3, slot=2, ref_char=""),
        CoordRec(id=f"{BOOK}:{PAGE}:3:3", col=3, slot=3, ref_char="衡")]
    write_product(ctx, "align_ref", PAGE,
                  align_ref=PageAlignRef(page=PAGE, anchored=False, coord=coord))
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}, sa


def test_occluded_cells_are_never_admitted_and_default_to_reference(tmp_path, monkeypatch):
    got, sa = _run_seed(tmp_path, monkeypatch)
    r3 = got[3]
    assert not r3.admit and r3.doubts == ["occluded"], (r3.channel, r3.doubts)
    assert r3.char == "衡" and r3.evidence["occluded"]["via"] == "coord"
    r2 = got[2]
    assert not r2.admit and r2.char is None and r2.evidence["occluded"]["ref_blank"]
    assert got[15].admit, "印章外的格照常放行"
    assert sa.n_auto == 1 and sa.n_review == 2


def test_gate_off_restores_old_behaviour(tmp_path, monkeypatch):
    got, _ = _run_seed(tmp_path, monkeypatch, params=SeedAdmitParams(occluded_gate=False))
    assert got[3].admit and got[2].admit


# ── 文本层 ────────────────────────────────────────────────────────────────
def _cell(slot):
    return CellRec(slot=slot, pos=slot, y0=0, y1=0, x0=0, x1=0, kind="char", order=slot)


def test_text_layer_outputs_default_char_and_skips_blank_fake_cells():
    rec = AdmitRec(id="", slot=3, admit=False, char="衡", doubts=["occluded"],
                   evidence={"occluded": {"density": 9.0, "via": "coord"}})
    s = _to_slot("vol03", 3, 5, rec, _cell(3))
    assert s.char == "衡" and s.is_text and not s.unreadable
    blank = AdmitRec(id="", slot=1, admit=False, char=None, doubts=["occluded"],
                     evidence={"occluded": {"density": 9.0, "via": "coord_blank", "ref_blank": True}})
    b = _to_slot("vol03", 3, 5, blank, _cell(1))
    assert b.excluded and not b.is_text
    # 对照：普通的未放行格照旧不出字（口径没被放宽）
    plain = AdmitRec(id="", slot=4, admit=False, char="衡", doubts=["库 unsure"])
    assert _to_slot("vol03", 3, 5, plain, _cell(4)).char is None
