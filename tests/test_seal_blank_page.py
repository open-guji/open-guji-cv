# -*- coding: utf-8 -*-
"""盖章空栏判空（`seal_blank_page`，2026-10-09，道 B 规格 overview#493）。

全部造数据：合成印模板、合成页、合成格，不读真书、不依赖 `tests/fixtures`。
测三件事：①`occlusion.seal_blank_cells` 能在窗口先验内找到印框、按重叠挑格；
②`seed_admit._seal_blank_flip` 的格级保险（坐标无字 ∧ 非强通道 ∧ 非人裁）；
③挪过去的格能被 `_review_lanes_pass` 的 coord_blank 分支接住，且开关关时参数 dump 不变。
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps import occlusion
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _review_lanes_pass,
                                           _seal_blank_flip)

TPL_H, TPL_W = 680, 660
SEAL_XY = (830, 330)          # 与 occlusion.SEAL_WIN_XY 同一先验中心，印放在这里


def _template(seed: int = 0) -> np.ndarray:
    """合成印：白底上一圈随机斑点（有结构、与噪声页的 NCC 很低）。"""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:TPL_H, 0:TPL_W]
    r = np.hypot(yy - TPL_H / 2, xx - TPL_W / 2)
    ring = (r > 200) & (r < 300)
    spots = rng.random((TPL_H, TPL_W)) < 0.5
    tpl = np.full((TPL_H, TPL_W), 255, np.uint8)
    tpl[ring & spots] = 0
    return tpl


def _page(with_seal: bool, tpl: np.ndarray | None = None, seed: int = 1) -> np.ndarray:
    H, W = 1250, 1700
    if with_seal:
        page = np.full((H, W), 255, np.uint8)
        x, y = SEAL_XY
        page[y:y + TPL_H, x:x + TPL_W] = tpl
        return page
    rng = np.random.default_rng(seed)
    return np.where(rng.random((H, W)) < 0.3, 0, 255).astype(np.uint8)


def _quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _cells(*boxes):
    """boxes: (slot, quad) 列表 → Step3 字格的最小替身（只要 columns/cells/slot/sub/quad_page）。"""
    cells = [SimpleNamespace(slot=s, sub="", quad_page=q) for s, q in boxes]
    return SimpleNamespace(columns=[SimpleNamespace(col=3, cells=cells)])


# ── ① 印框检测与按重叠挑格 ─────────────────────────────────────────────

def test_seal_found_and_overlap_picks_cells():
    tpl = _template()
    gray = _page(True, tpl)
    cells = _cells(
        (1, _quad(900, 400, 950, 450)),      # 全在印框内 → 入选
        (2, _quad(1460, 400, 1510, 450)),    # 印框内 30/50 ≈ 0.6 → 入选
        (3, _quad(1475, 400, 1525, 450)),    # 印框内 15/50 = 0.3 → 不入选
        (4, _quad(100, 400, 150, 450)),      # 印框外 → 不入选
    )
    hit = occlusion.seal_blank_cells(gray, cells, templates=[tpl], thr=0.35, overlap=0.5)
    assert set(hit) == {(3, 1, ""), (3, 2, "")}
    assert hit[(3, 1, "")]["seal_score"] >= 0.9
    assert 0.5 <= hit[(3, 2, "")]["overlap"] < 0.7


def test_no_seal_page_gives_nothing():
    tpl = _template()
    gray = _page(False)
    cells = _cells((1, _quad(900, 400, 950, 450)))
    assert occlusion.seal_blank_cells(gray, cells, templates=[tpl], thr=0.35, overlap=0.5) == {}


def test_threshold_above_score_gives_nothing():
    tpl = _template()
    gray = _page(True, tpl)
    cells = _cells((1, _quad(900, 400, 950, 450)))
    assert occlusion.seal_blank_cells(gray, cells, templates=[tpl], thr=1.01, overlap=0.5) == {}


def test_no_templates_gives_nothing():
    gray = _page(True, _template())
    cells = _cells((1, _quad(900, 400, 950, 450)))
    assert occlusion.seal_blank_cells(gray, cells, templates=[], thr=0.35, overlap=0.5) == {}


def test_repo_templates_load():
    tpls = occlusion.load_seal_templates()
    assert len(tpls) == 5 and all(t.shape == (TPL_H, TPL_W) for t in tpls)


# ── ② 格级保险 _seal_blank_flip ───────────────────────────────────────

def _col(*recs):
    return ColumnAdmit(col=3, chars=list(recs))


def _rec(rid, slot, **kw):
    base = dict(id=rid, slot=slot, sub=None, admit=True, channel="context", char="一",
                provenance="context", doubts=[], evidence={})
    base.update(kw)
    return AdmitRec(**base)


SEAL = {(3, s, ""): {"seal_score": 0.5, "overlap": 0.9} for s in range(1, 9)}


def test_flip_context_admitted_blank_cell():
    r = _rec("a", 1)
    out = [_col(r)]
    n = _seal_blank_flip(out, SEAL, coord={"a": ""})
    assert n == 1
    assert (r.admit, r.channel, r.char, r.provenance) == (False, None, None, "")
    assert "occluded" in r.doubts
    assert r.evidence["occluded"]["via"] == "coord_blank"
    assert r.evidence["occluded"]["ref_blank"] is True


def test_strong_channel_admitted_cell_untouched():
    r = _rec("a", 1, channel="match_solo")
    assert _seal_blank_flip([_col(r)], SEAL, coord={}) == 0
    assert r.admit and r.channel == "match_solo" and r.char == "一"


def test_coord_char_present_untouched():
    r = _rec("a", 1)
    assert _seal_blank_flip([_col(r)], SEAL, coord={"a": "土"}) == 0
    assert r.admit and r.char == "一"


def test_coord_placeholder_counts_as_char():
    r = _rec("a", 1)
    assert _seal_blank_flip([_col(r)], SEAL, coord={"a": "〓"}) == 0
    assert r.admit and r.char == "一"


def test_human_and_excluded_untouched():
    h = _rec("h", 1, channel="human", provenance="human")
    x = _rec("x", 2, doubts=["excluded"])
    assert _seal_blank_flip([_col(h, x)], SEAL, coord={}) == 0
    assert h.admit and x.admit


def test_already_occluded_cell_untouched():
    r = _rec("a", 1, admit=False, channel=None, char="土", doubts=["occluded"],
             evidence={"occluded": {"via": "coord", "density": 9.0}})
    assert _seal_blank_flip([_col(r)], SEAL, coord={}) == 0
    assert r.evidence["occluded"]["density"] == 9.0


def test_cell_outside_seal_untouched():
    r = _rec("a", 9)                       # 不在 SEAL 候选里
    assert _seal_blank_flip([_col(r)], SEAL, coord={}) == 0
    assert r.admit


def test_pending_blank_cell_gets_occluded_mark_but_not_counted():
    r = _rec("a", 1, admit=False, channel=None, char=None, provenance="", doubts=[])
    assert _seal_blank_flip([_col(r)], SEAL, coord={}) == 0
    assert not r.admit and "occluded" in r.doubts


# ── ③ 挪过去的格被 lane_seal 的 coord_blank 分支接住；开关关时参数不变 ─────

class _VStub:
    def semantic(self, ch):
        return ch


def test_flipped_cell_is_judged_non_char_by_lane_seal():
    r = _rec("a", 1)
    out = [_col(r)]
    _seal_blank_flip(out, SEAL, coord={"a": ""})
    p = SeedAdmitParams(lane_seal=True)
    n = _review_lanes_pass(p, out, mmap={}, amap={}, coord={"a": ""}, vmap=_VStub(),
                           witnesses_fn=None)
    assert n == 1
    assert r.admit is True and r.channel == "seal" and r.char is None


def test_seal_blank_params_off_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert not {"seal_blank_page", "seal_blank_thr", "seal_blank_overlap"} & set(d)
    on = SeedAdmitParams(seal_blank_page=True).model_dump()
    assert on["seal_blank_page"] is True and on["seal_blank_thr"] == 0.35


# ── 第四条保险：格内模板外墨 < seal_blank_ink_out（Haiku 试验 7，道 A 量法 overview#493）────

def test_ink_out_only_template_strokes_stays_blank():
    # ① 格里只有模板笔画（落在覆盖区内）→ 模板外墨 ≈ 0 → 仍判空
    tpl = _template()
    gray = _page(True, tpl)
    cells = _cells((1, _quad(880, 620, 980, 720)))      # 落在环带内，有模板笔画
    hit = occlusion.seal_blank_cells(gray, cells, templates=[tpl], thr=0.35, overlap=0.5,
                                     ink_out=0.005)
    assert (3, 1, "") in hit
    assert hit[(3, 1, "")]["ink_out"] == 0.0


def test_ink_out_uncovered_ink_excludes_cell():
    # ② 格里有模板笔画，覆盖区外另有一横一竖（占比 ≈ 0.02 > 0.01）→ 不判空（退出候选）
    tpl = _template()
    gray = _page(True, tpl)
    gray[700, 1110:1210] = 0          # 横：圆心区，模板外
    gray[620:720, 1160] = 0           # 竖：圆心区，模板外
    cells = _cells((1, _quad(1110, 620, 1210, 720)))
    assert occlusion.seal_blank_cells(gray, cells, templates=[tpl], thr=0.35, overlap=0.5,
                                      ink_out=0.005) == {}
    free = occlusion.seal_blank_cells(gray, cells, templates=[tpl], thr=0.35, overlap=0.5)
    assert free[(3, 1, "")]["ink_out"] > 0.01          # 不过滤时仍在，只是带着外墨值


def test_ink_out_threshold_boundary():
    # ③ 边界：ink_out 恰等于门槛 → 退出（>=）；略低 → 保留
    tpl = _template()
    base = _page(True, tpl)
    cells = _cells((1, _quad(1110, 620, 1210, 720)))    # 100×100 = 10000 px，圆心区无覆盖
    on_edge = base.copy()
    on_edge[700, 1110:1160] = 0                          # 50 px → 50/10000 = 0.005
    assert occlusion.seal_blank_cells(on_edge, cells, templates=[tpl], thr=0.35, overlap=0.5,
                                      ink_out=0.005) == {}
    just_under = base.copy()
    just_under[700, 1110:1159] = 0                       # 49 px → 0.0049
    kept = occlusion.seal_blank_cells(just_under, cells, templates=[tpl], thr=0.35, overlap=0.5,
                                      ink_out=0.005)
    assert kept[(3, 1, "")]["ink_out"] == 0.0049


def test_ink_out_param_dump_rule():
    # ④ 开关关：dump 不含 seal_blank_ink_out；开关开：含，缺省 0.005
    from open_guji_cv.steps.seed_admit import SeedAdmitParams as SP
    assert "seal_blank_ink_out" not in SP().model_dump()
    on = SP(seal_blank_page=True).model_dump()
    assert on["seal_blank_ink_out"] == 0.005
