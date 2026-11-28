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
def _run_seed(tmp_path, monkeypatch, *, params=None, coord=None, fallback=None, seals=None, align=None,
              lib=("same", 0.999)):
    img, cells = _page_and_cells()
    ctx = make_ctx(tmp_path, make_book(BOOK), raw={PAGE: img}, monkeypatch=monkeypatch)
    if params is not None:
        ctx = RunContext(ctx.book, ctx.store, ctx.cache, params={"char_decide": params},
                         log=lambda s: None)
        ctx._raw[PAGE] = img
    # 列 3：slot 3 在印章里（库 same 0.999，平时 match_solo 直接放行）；slot 2 是印章切出的假格；
    # slot 15 在印章外，照常放行。
    recs = [MatchRec(id=f"{BOOK}:{PAGE}:3:{s}", slot=s, verdict=lib[0] if s != 15 else "same",
                     char="衡" if (lib[0] == "same" or s == 15) else None, cov=lib[1] if s != 15 else 0.999,
                     candidates=[("衡", lib[1] if s != 15 else 0.999)]) for s in (2, 3, 15)]
    write_product(ctx, "glyph_match", PAGE,
                  glyph_match=PageMatch(page=PAGE, columns=[ColumnMatch(col=3, ok=True, chars=recs)]))
    write_product(ctx, "context_decide", PAGE,
                  context_decision=page_decision(PAGE, BOOK, recs=[], col=3))
    write_product(ctx, "row_segment", PAGE, cells=cells)
    coord = coord if coord is not None else [
        CoordRec(id=f"{BOOK}:{PAGE}:3:2", col=3, slot=2, ref_char=""),
        CoordRec(id=f"{BOOK}:{PAGE}:3:3", col=3, slot=3, ref_char="衡")]
    if seals is not None:
        from open_guji_cv.products.kinds.seals import PageSeals
        write_product(ctx, "seal_detect", PAGE, seals=PageSeals(page=PAGE, width=1100, height=2300, seals=seals))
    write_product(ctx, "align_ref", PAGE,
                  align_ref=PageAlignRef(page=PAGE, anchored=bool(align), coord=coord, chars=align or [],
                                         coord_fallback=fallback or {}))
    sa = STEPS["char_decide"].run_page(ctx, PAGE)["char_decide"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}, sa


def test_occluded_cells_are_never_admitted_and_default_to_reference(tmp_path, monkeypatch):
    got, sa = _run_seed(tmp_path, monkeypatch, params=SeedAdmitParams(lane_seal=False))   # 印章区补放另测（test_seed_admit_lanes）
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


def test_past_leaf_column_defaults_to_blank(tmp_path, monkeypatch):
    """1.29：列过了整理本这半叶末行（卷末印页）→ 无坐标字的遮挡格记 coord_blank，不再是 via=none。"""
    from open_guji_cv.steps.align_ref_coord import COORD_PAST_LEAF
    p = SeedAdmitParams(lane_seal=False)
    got, _ = _run_seed(tmp_path, monkeypatch, params=p, coord=[], fallback={"3": COORD_PAST_LEAF})
    assert got[3].char is None and got[3].evidence["occluded"]["via"] == "coord_blank"
    assert got[3].evidence["occluded"]["ref_blank"]
    got, _ = _run_seed(tmp_path / "b", monkeypatch, params=p, coord=[], fallback={"3": "列行对应不成立"})
    assert got[3].evidence["occluded"]["via"] == "none"


def test_ref_empty_column_defaults_to_blank_only_when_switched_on(tmp_path, monkeypatch):
    """`occluded_ref_empty_blank`（书级，缺省关）：整理本这一行是空的（`整理本行为空`）→ 印下无坐标字的遮挡格记 coord_blank。"""
    fb = {"3": "整理本行为空"}
    got, _ = _run_seed(tmp_path, monkeypatch, params=SeedAdmitParams(lane_seal=False), coord=[], fallback=fb)
    assert got[3].evidence["occluded"]["via"] == "none"          # 缺省关：行为不变
    p = SeedAdmitParams(lane_seal=False, occluded_ref_empty_blank=True)
    got, _ = _run_seed(tmp_path / "b", monkeypatch, params=p, coord=[], fallback=fb)
    assert got[3].char is None and got[3].evidence["occluded"]["via"] == "coord_blank"
    got, _ = _run_seed(tmp_path / "c", monkeypatch, params=p, coord=[], fallback={"3": "列行对应不成立"})
    assert got[3].evidence["occluded"]["via"] == "none"
    assert "occluded_ref_empty_blank" not in SeedAdmitParams(db_path="x").model_dump()


def _seal_hits(monkeypatch):
    import open_guji_cv.steps.occlusion as occ_mod
    monkeypatch.setattr(occ_mod, "page_occluded", lambda ctx, page, p: {(c, s, ""): 9.0 for c, s in SEAL})


def test_manual_seal_cells_default_to_blank_only_when_switched_on(tmp_path, monkeypatch):
    """`occluded_manual_seal_blank`（书级，缺省关）：人定印框（`source="manual"`）压着、没有坐标对位字的遮挡格
    记 coord_blank（全唐文 046–060，QTW 11-21）；算法认的印、坐标对位给了字的格不动。"""
    from open_guji_cv.products.kinds.seals import Seal
    _seal_hits(monkeypatch)
    coord = [CoordRec(id=f"{BOOK}:{PAGE}:3:2", col=3, slot=2, ref_char="衡")]

    def run(path, params, source, lib=("diff", 0.7)):   # 印框：列 3（x 700..800）slot 2..8（y 200..900）
        seal = Seal(kind="stain", bbox=(700, 200, 800, 900), score=1.0, source=source)
        return _run_seed(path, monkeypatch, params=params, coord=coord, seals=[seal], lib=lib)[0]

    off = run(tmp_path / "a", SeedAdmitParams(lane_seal=False), "manual")
    assert off[3].evidence["occluded"]["via"] == "none"                  # 缺省关：行为不变
    p = SeedAdmitParams(lane_seal=False, occluded_manual_seal_blank=True)
    on = run(tmp_path / "b", p, "manual")
    assert on[3].char is None and on[3].evidence["occluded"]["via"] == "coord_blank"
    assert on[3].evidence["occluded"]["ref_blank"]
    assert on[2].char == "衡" and on[2].evidence["occluded"]["via"] == "coord"   # 印压真字：照旧
    algo = run(tmp_path / "c", p, "frame")
    assert algo[3].evidence["occluded"]["via"] == "none"                 # 算法认的印不受影响
    lanes = run(tmp_path / "d", SeedAdmitParams(occluded_manual_seal_blank=True), "manual")
    assert lanes[3].admit and lanes[3].char is None                      # R5 判非字，不进待审
    # 印压真字保险：库认得出（unsure 首位 ≥ occluded_seal_keep_cov，或 same）就不判空
    for lib in (("unsure", 0.95), ("same", 0.99)):
        kept = run(tmp_path / f"e{lib[0]}", p, "manual", lib=lib)
        assert kept[3].evidence["occluded"]["via"] == "none", lib
    low = run(tmp_path / "f", p, "manual", lib=("unsure", 0.91))
    assert low[3].evidence["occluded"]["via"] == "coord_blank"
    assert "occluded_seal_keep_cov" not in SeedAdmitParams(db_path="x").model_dump()
    assert "occluded_manual_seal_blank" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", occluded_manual_seal_blank=True).model_dump()["occluded_manual_seal_blank"]


def test_align_char_on_seal_does_not_block_past_leaf_blank(tmp_path, monkeypatch):
    """`occluded_seal_align_yield`（书级，缺省关）：过了半叶末行的列，印纹上被现役对位硬配的字不挡 past_leaf 判空，
    那一格的 align 默认字也让位给 coord_blank（全唐文 057 p90 8:19、9:21，A22 11-21）。"""
    from open_guji_cv.products.kinds.recog import AlignRec
    from open_guji_cv.steps.align_ref_coord import COORD_PAST_LEAF
    _seal_hits(monkeypatch)
    align = [AlignRec(id=f"{BOOK}:{PAGE}:3:2", col=3, slot=2, align_char="一", align_op="equal")]
    fb = {"3": COORD_PAST_LEAF}
    off, _ = _run_seed(tmp_path / "a", monkeypatch, params=SeedAdmitParams(lane_seal=False), coord=[],
                       fallback=fb, align=align, lib=("diff", 0.7))
    assert off[2].evidence["occluded"]["via"] == "align" and off[3].evidence["occluded"]["via"] == "none"
    p = SeedAdmitParams(lane_seal=False, occluded_seal_align_yield=True)
    on, _ = _run_seed(tmp_path / "b", monkeypatch, params=p, coord=[], fallback=fb, align=align, lib=("diff", 0.7))
    assert on[2].char is None and on[2].evidence["occluded"]["via"] == "coord_blank"
    assert on[3].char is None and on[3].evidence["occluded"]["via"] == "coord_blank"
    # 遮挡格外（slot 15）有现役对位字：整列照旧不算空列
    out = align + [AlignRec(id=f"{BOOK}:{PAGE}:3:15", col=3, slot=15, align_char="衡", align_op="equal")]
    keep, _ = _run_seed(tmp_path / "c", monkeypatch, params=p, coord=[], fallback=fb, align=out, lib=("diff", 0.7))
    assert keep[2].evidence["occluded"]["via"] == "align" and keep[3].evidence["occluded"]["via"] == "none"
    assert "occluded_seal_align_yield" not in SeedAdmitParams(db_path="x").model_dump()


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


def test_pua_placeholder_is_not_used_as_default(tmp_path, monkeypatch):
    """daizhige 逐列本里没码表的 PUA 生僻字记 `〓`：知道这儿有字、不知道是哪个——默认字留空。"""
    coord = [CoordRec(id=f"{BOOK}:{PAGE}:3:3", col=3, slot=3, ref_char="〓")]
    got, _ = _run_seed(tmp_path, monkeypatch, coord=coord)
    assert not got[3].admit and got[3].char is None
    assert got[3].evidence["occluded"]["via"] == "coord_pua"


# ── 清楚的字救回 `occluded_rescue_ink`（GUJI-555，vol04 p130）────────────────────
def _ctx_with(img, cells):
    from types import SimpleNamespace
    return SimpleNamespace(product=lambda kind, page: cells, raw_page=lambda page: img)


def _with_clear_char(cell=(3, 4)):
    """遮挡块里 (3,4) 这一格写了一个清楚的大字（一大块实心墨），其余仍是斑点。"""
    img, cells = _page_and_cells()
    c, s = cell
    x0, y0 = 100 + (NCOL - c) * CW, 100 + (s - 1) * CH
    img[y0 + 20:y0 + 80, x0 + 25:x0 + 75] = 0
    return img, cells, cell


def test_rescue_is_off_by_default_so_clear_char_stays_occluded():
    from open_guji_cv.steps.occlusion import page_occluded
    img, cells, cell = _with_clear_char()
    hit = page_occluded(_ctx_with(img, cells), PAGE, SeedAdmitParams())
    assert (cell[0], cell[1], "") in hit


def test_callers_without_the_field_keep_working():
    """`feedback.consumers`／`cell_shrink` 传的参数对象可能没有这个字段——getattr 缺省 0＝关。"""
    from types import SimpleNamespace
    from open_guji_cv.steps.occlusion import page_occluded
    img, cells, cell = _with_clear_char()
    p = SimpleNamespace(occluded_min_density=4.0, occluded_min_cells=12, occluded_min_cols=3,
                        occluded_min_peak=8.0, occluded_min_contrast=2.5)
    assert (cell[0], cell[1], "") in page_occluded(_ctx_with(img, cells), PAGE, p)


import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
