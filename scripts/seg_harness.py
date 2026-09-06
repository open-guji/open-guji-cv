# -*- coding: utf-8 -*-
"""Step3 切分离线复现台：不重跑管线，直接在金标列上量任何改动。

    python scripts/seg_harness.py [--book vol01] [--variant NAME] [--diag] [--all-body]

做三件事：
  1. 复现：用与 RowSegmentStep 完全相同的入参调 segment_column，核对与现役产物一致
     （--variant baseline 时格线应逐条相同；不同就说明台子搭错了）。
  2. 金标：char-segmentation/touching-cuts（moved / ok / overlap，排除带干扰标签的）
     ——现役/改动后切点 vs 人工理想位置的像素误差。
  3. 尺子：这些列上的 R2 / R2x / R2s（口径同 eval/rulers.py）。

--variant 通过 VARIANTS 表给 fit_row_boundaries / segment_column 换参数或换实现，
改动都写在这个文件里试，试对了再搬进 row_boundaries.py。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.rulers import INK_ON_LINE, STUCK_FLOOR, _col_profile  # noqa: E402
from open_guji_cv.gold.store import GoldStore  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.steps.row_segment import RowSegmentParams  # noqa: E402
from open_guji_cv.utils import row_boundaries as RB  # noqa: E402

SHARD = "char-segmentation/touching-cuts"


# ── 变体：改这里 ───────────────────────────────────────────────────
# 每个变体是一个 dict：`fit` 覆盖 fit_row_boundaries 的关键字参数；`patch` 是可选的
# 函数，接收 RB 模块，可以替换其中的函数（monkeypatch），返回恢复用的闭包。
def _dp_blank_elastic(x1, x2, valleys, valley_ink, period, eps, lo_ratio, hi_ratio,
                      y1_max_frac, y2_max_frac, lam, n_slots, top_slack=0.0,
                      curve=None, blank_thresh=0.0, blank_min_gap=2.0, blank_cost=0.0,
                      skip_cost=0.0, clean_ink=0.02, tail_trim=False):
    """与 RB._bounded_elastic_dp 同构，只改 step_cost：
    两候选之间若**没有墨**（curve 在区间内最大值 < blank_thresh），这一格是空白格，
    间距只需 ≥ blank_min_gap、≤ hi_ratio·period，且不吃 λ 的间距惩罚。
    动机（2026-09-05 切线金标 250 条）：列里少一个字（空白格）时，硬下界 0.7·period 逼 DP
    把缺的那一格摊到邻近 2–4 个字上，每条格线偏 30–58px（局部滑格），列尾尤甚。
    """
    import numpy as np
    y1_max = y1_max_frac * period; y2_max = y2_max_frac * period
    x1_eff = x1 - top_slack
    cand0 = [(v, ink) for v, ink in zip(valleys, valley_ink) if x1_eff <= v <= x1 + y1_max]
    candN = [(v, ink) for v, ink in zip(valleys, valley_ink) if x2 - y2_max <= v <= x2]
    if top_slack > 0:
        head = max(0.0, x1 - top_slack)
        if not any(abs(v - head) < 1e-6 for v, _ in cand0):
            cand0.append((head, 0.0))
    if not cand0:
        cand0 = [(x1 + y1_max * 0.4, 0.05)]
    if not candN:
        candN = [(x2 - y2_max * 0.4, 0.05)]
    n_interior = n_slots - 1
    mid = sorted([(v, ink) for v, ink in zip(valleys, valley_ink) if x1_eff < v < x2], key=lambda t: t[0])
    m_count = len(mid)
    if m_count < n_interior:
        return None
    # 前缀最大值表：O(1) 查区间内墨的最大值
    cmax = None
    if curve is not None:
        cmax = np.asarray(curve, dtype=np.float64)
    def is_blank(ya, yb):
        if cmax is None: return False
        a, b = int(round(min(ya, yb))), int(round(max(ya, yb)))
        if b <= a: return True
        seg = cmax[max(0, a):min(len(cmax), b + 1)]
        return seg.size == 0 or float(seg.max()) < blank_thresh
    # 候选里的"净谷"（墨 ≤ clean_ink）位置，用来数一个字格内部跳过了几条干净的缝
    clean_pos = np.array([v for v, ink in zip(valleys, valley_ink) if ink <= clean_ink], dtype=np.float64)
    def n_clean_inside(ya, yb):
        if skip_cost <= 0 or clean_pos.size == 0: return 0
        return int(((clean_pos > ya + 1e-6) & (clean_pos < yb - 1e-6)).sum())
    def ink_end(ya, yb):
        """[ya, yb] 内最后一行有墨的位置（没有就返回 ya）——列尾格的高度按墨算，不算尾部空白/残渣。"""
        if cmax is None: return yb
        a, b = int(round(ya)), int(round(yb))
        seg = cmax[max(0, a):min(len(cmax), b + 1)]
        idx = np.nonzero(seg >= blank_thresh)[0]
        return (a + int(idx[-1])) if idx.size else ya
    def step_cost(y_prev, y, last=False):
        gap = y - y_prev
        if gap < blank_min_gap: return None
        if is_blank(y_prev, y):
            return blank_cost if gap <= hi_ratio * period else None
        g = gap
        if last and tail_trim:
            g = max(lo_ratio * period, ink_end(y_prev, y) - y_prev)   # 尾部空白不计入格高
        if not (lo_ratio * period <= g <= hi_ratio * period): return None
        return lam * ((g - period) / period) ** 2 + skip_cost * n_clean_inside(y_prev, y)
    best = None
    for v0, _ink0 in cand0:
        dp_cost = np.full((n_interior, m_count), np.inf); dp_prev = np.full((n_interior, m_count), -1, dtype=int)
        for m in range(m_count):
            y, ink = mid[m]; c = step_cost(v0, y)
            if c is not None: dp_cost[0, m] = c + ink + eps
        for k in range(1, n_interior):
            for m in range(m_count):
                y, ink = mid[m]; best_c, best_p = np.inf, -1
                for mp in range(m):
                    if not np.isfinite(dp_cost[k - 1, mp]): continue
                    c = step_cost(mid[mp][0], y)
                    if c is None: continue
                    total = dp_cost[k - 1, mp] + c + ink + eps
                    if total < best_c: best_c, best_p = total, mp
                dp_cost[k, m] = best_c; dp_prev[k, m] = best_p
        k_last = n_interior - 1
        for m in range(m_count):
            if not np.isfinite(dp_cost[k_last, m]): continue
            y, _ = mid[m]
            for vN, _inkN in candN:
                c = step_cost(y, vN, last=True)
                if c is None: continue
                total = dp_cost[k_last, m] + c
                if best is None or total < best[0]:
                    path = [0.0] * n_interior; idx = m
                    for kk in range(k_last, -1, -1):
                        path[kk] = mid[idx][0]; idx = dp_prev[kk, idx]
                        if idx == -1: break
                    best = (total, v0, path, vN)
    if best is None: return None
    _, v0, path, vN = best
    return [v0] + path + [vN]


def _patch_blank_elastic(blank_min_gap=2.0, blank_frac=None, blank_cost=0.0, skip_cost=0.0, blank_min_frac=0.0,
                         tail_trim=False, hi_r=None, lo_r=None):
    """把 fit_row_boundaries 换成会把 curve 交给 DP 的版本（其余逐行照抄 RB 的实现）。"""
    import numpy as np
    orig_fit = RB.fit_row_boundaries
    def fit(row_proj, dst_w, border_top, border_bottom, period, n_slots=21, eps=0.01, lam=0.3,
            lo_ratio=0.7, hi_ratio=1.35, y1_max_frac=0.5, y2_max_frac=0.3, blank_thresh_frac=0.08,
            synth_step=20, top_slack=0.0, snap_raw=3):
        curve = RB.smooth_curve(np.asarray(row_proj, dtype=np.float64))
        valleys_all = RB.find_valleys(curve, dst_w)
        thresh = blank_thresh_frac * dst_w
        intervals = RB.find_blank_intervals(curve, thresh)
        valid = list(valleys_all); valley_ink = [curve[v] / dst_w for v in valid]
        synth_guard = max(6, synth_step // 3); synth = []; synth_ink = []
        for lo, hi in intervals:
            y = lo
            while y <= hi:
                if all(abs(y - v) >= synth_guard for v in valid):
                    synth.append(float(y)); synth_ink.append(float(curve[int(y)]) / dst_w if 0 <= int(y) < len(curve) else 0.03)
                y += synth_step
        all_v = np.array(valid + synth, dtype=np.float64); all_i = np.array(valley_ink + synth_ink, dtype=np.float64)
        order = np.argsort(all_v); all_v, all_i = all_v[order], all_i[order]
        bt = (blank_frac if blank_frac is not None else blank_thresh_frac) * dst_w
        b = _dp_blank_elastic(border_top, border_bottom, all_v, all_i, period, eps,
                              lo_r if lo_r is not None else lo_ratio, hi_r if hi_r is not None else hi_ratio,
                              y1_max_frac, y2_max_frac, lam, n_slots, top_slack,
                              curve=curve, blank_thresh=bt, blank_min_gap=max(blank_min_gap, blank_min_frac * period),
                              blank_cost=blank_cost, skip_cost=skip_cost, tail_trim=tail_trim)
        if b is None: return None
        b = RB._snap_to_raw_minimum(b, np.asarray(row_proj, dtype=np.float64), snap_raw)
        return RB.RowBoundaryResult(boundaries=b, blank_intervals=intervals, valleys=valleys_all, period=period)
    RB.fit_row_boundaries = fit
    return lambda: setattr(RB, "fit_row_boundaries", orig_fit)


_INK_SLICE = {}


def _patch_seamcost(band=20, weight=1.0):
    """候选波谷的位置代价改成"这里能找到的最干净的缝有多少墨"（按列宽归一）。
    挤排列里没有干净的行，但常有干净的折线；行墨代价会把锚点放到高字内部的空隙上
    （vol01:10:5:6 典/道 偏 39px），缝代价会把它放到能绕开的地方。"""
    import numpy as np
    from open_guji_cv.utils.seam import find_seam, seam_ink
    orig_proj = RB.row_ink_projection
    orig_fit = RB.fit_row_boundaries

    def proj(col_gray, x_lo=0, x_hi=None, ink_threshold=128):
        _INK_SLICE["ink"] = (col_gray[:, x_lo:x_hi] < ink_threshold)
        return orig_proj(col_gray, x_lo, x_hi, ink_threshold)

    def fit(row_proj, dst_w, border_top, border_bottom, period, n_slots=21, eps=0.01, lam=0.3,
            lo_ratio=0.7, hi_ratio=1.5, y1_max_frac=0.5, y2_max_frac=0.3, blank_thresh_frac=0.08,
            synth_step=20, top_slack=0.0, snap_raw=3, blank_cost=0.05, tail_trim=True):
        ink = _INK_SLICE.get("ink")
        curve = RB.smooth_curve(np.asarray(row_proj, dtype=np.float64))
        valleys_all = RB.find_valleys(curve, dst_w)
        thresh = blank_thresh_frac * dst_w
        intervals = RB.find_blank_intervals(curve, thresh)
        valid = list(valleys_all)
        def cost_of(v):
            row = float(curve[int(v)]) / dst_w
            if ink is None or row <= 0.02:
                return row
            sm = find_seam(ink, int(v), band=band)
            return min(row, weight * seam_ink(ink, sm) / dst_w)
        valley_ink = [cost_of(v) for v in valid]
        synth_guard = max(6, synth_step // 3); synth = []; synth_ink = []
        for lo, hi in intervals:
            y = lo
            while y <= hi:
                if all(abs(y - v) >= synth_guard for v in valid):
                    synth.append(float(y)); synth_ink.append(float(curve[int(y)]) / dst_w if 0 <= int(y) < len(curve) else 0.03)
                y += synth_step
        all_v = np.array(valid + synth, dtype=np.float64); all_i = np.array(valley_ink + synth_ink, dtype=np.float64)
        order = np.argsort(all_v); all_v, all_i = all_v[order], all_i[order]
        b = RB._bounded_elastic_dp(border_top, border_bottom, all_v, all_i, period, eps, lo_ratio, hi_ratio,
                                   y1_max_frac, y2_max_frac, lam, n_slots, top_slack,
                                   curve=curve, blank_thresh=thresh, blank_cost=blank_cost, tail_trim=tail_trim)
        if b is None:
            return None
        b = RB._snap_to_raw_minimum(b, np.asarray(row_proj, dtype=np.float64), snap_raw)
        return RB.RowBoundaryResult(boundaries=b, blank_intervals=intervals, valleys=valleys_all, period=period)

    RB.row_ink_projection = proj
    RB.fit_row_boundaries = fit
    def restore():
        RB.row_ink_projection = orig_proj
        RB.fit_row_boundaries = orig_fit
    return restore


VARIANTS: dict[str, dict] = {
    "baseline": {},
    "seamcost": {"patch": lambda RB_: _patch_seamcost()},
    "seamcost30": {"patch": lambda RB_: _patch_seamcost(band=30)},
    "snap6": {"fit": {"snap_raw": 6}},
    "snap10": {"fit": {"snap_raw": 10}},
    "blank": {"patch": lambda RB_: _patch_blank_elastic()},
    "blank_snap6": {"patch": lambda RB_: _patch_blank_elastic(), "fit": {"snap_raw": 6}},
    "blank_t05": {"patch": lambda RB_: _patch_blank_elastic(blank_frac=0.05)},
    # 旋钮网格：空白格固定代价 / 字格内跳过净谷代价 / 空白格最小高
    "b05":      {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05)},
    "b10":      {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.10)},
    "b20":      {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.20)},
    "s05":      {"patch": lambda RB_: _patch_blank_elastic(skip_cost=0.05)},
    "b10s05":   {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.10, skip_cost=0.05)},
    "b10s10":   {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.10, skip_cost=0.10)},
    "b10m3":    {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.10, blank_min_frac=0.3)},
    "skiponly": {"patch": lambda RB_: _patch_blank_elastic(blank_cost=1e9, skip_cost=0.05)},
    "b05_tail":       {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05, tail_trim=True)},
    "b05_hi145":      {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05, hi_r=1.45)},
    "b05_hi150":      {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05, hi_r=1.5)},
    "b05_hi160":      {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05, hi_r=1.6)},
    "b05_tail_hi150": {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05, tail_trim=True, hi_r=1.5)},
    "b05_tail_hi150_lo60": {"patch": lambda RB_: _patch_blank_elastic(blank_cost=0.05, tail_trim=True, hi_r=1.5, lo_r=0.6)},
}


def run_column(book, bk, gate, wins, gc, img, p: RowSegmentParams, fit_kw: dict):
    """与 RowSegmentStep.run_page 同一套入参。"""
    n_body = p.n_body_slots or bk.chars_per_line
    n_raised_col = max(p.n_raised, getattr(gc, "n_raised_hint", 0) or 0)
    return RB.segment_column(
        img, period=gate.period, n_body_slots=n_body, n_raised=n_raised_col,
        border_top=gc.border_top, border_bottom=gc.border_bottom, ref_w=gate.ref_w,
        top_slack=gc.top_slack, content_x=gc.content_x,
        ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio,
        raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu, **fit_kw)


def classify(prof: np.ndarray, y: int, period: float) -> str:
    h = len(prof)
    if not (0 <= y < h) or prof[y] <= INK_ON_LINE:
        return "clean"
    if float(prof[max(0, y - 12):min(h, y + 13)].min()) <= STUCK_FLOOR:
        return "R2"
    half = max(13, int(period / 2))
    if float(prof[max(0, y - half):min(h, y + half + 1)].min()) <= STUCK_FLOOR:
        return "R2x"
    return "R2s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--diag", action="store_true", help="逐条打印大幅错切的候选/墨量")
    ap.add_argument("--all-body", action="store_true", help="尺子统计扩到全部正文页（慢）")
    ap.add_argument("--json", default=None)
    ap.add_argument("--match", default="bi", choices=("bi", "nearest"),
                    help="bi = 按金标记的格线序号比；nearest = 金标位置到最近一条新格线的距离（格数结构变了时用）")
    ap.add_argument("--diag-new", action="store_true", help="打印变体误差 >20px 的条目及前后格线")
    a = ap.parse_args()
    var = VARIANTS[a.variant]
    fit_kw = dict(var.get("fit", {}))
    restore = var["patch"](RB) if var.get("patch") else None

    book = a.book
    bk = load_book(book)
    st, ic = ProductStore(), ImageCache()
    p = RowSegmentParams()
    gold = [i for i in GoldStore().list(SHARD) if i.anchor.book == book and i.status == "active"
            and not i.expected.get("tags") and i.expected.get("verdict") in ("moved", "ok", "overlap")]
    by_col: dict[tuple[int, int], list] = defaultdict(list)
    for it in gold:
        by_col[(it.anchor.page, it.anchor.col)].append(it)
    pages = sorted({pg for pg, _ in by_col})
    if a.all_body:
        from open_guji_cv.eval.touching import body_pages
        pages = sorted(set(pages) | set(body_pages(book)))

    errs, errs_base = [], []
    poly_new, poly_base = [], []
    from open_guji_cv.eval.touching import polyline_to_seam, seam_deviation
    gold_poly = [i for i in GoldStore().list(SHARD) if i.anchor.book == book and i.status == "active"
                 and i.expected.get("polyline") and len(i.expected["polyline"]) >= 2 and not i.expected.get("tags")]
    by_col_poly: dict[tuple[int, int], list] = defaultdict(list)
    for it in gold_poly:
        by_col_poly[(it.anchor.page, it.anchor.col)].append(it)
    pages = sorted(set(pages) | {pg for pg, _ in by_col_poly})
    rulers = Counter(); rulers_base = Counter()
    mismatch = 0; n_cols = 0; n_fail = 0
    diag_rows = []
    for pg in pages:
        gate = st.read(book, "column_gate", page_key(pg), "gate_manifest")
        wins = st.read(book, "column_warp", page_key(pg), "column_windows")
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if gate is None or cells is None or gate.period is None:
            continue
        prod = {c.col: c for c in cells.columns if c.ok}
        for gc in gate.columns:
            if not gc.admitted or gc.col not in prod:
                continue
            want_gold = (pg, gc.col) in by_col or (pg, gc.col) in by_col_poly
            if not want_gold and not a.all_body:
                continue
            path = ic.get(book, "column_image", column_key(pg, gc.col))
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
            if img is None:
                continue
            r = run_column(book, bk, gate, wins, gc, img, p, fit_kw)
            n_cols += 1
            if r is None:
                n_fail += 1
                continue
            prof = _col_profile(st, book, pg, gc.col)
            if prof is None:
                continue
            base_b = [float(b) for b in prod[gc.col].boundaries]
            new_b = [float(b) for b in r.boundaries]
            if a.variant == "baseline" and [round(x) for x in base_b] != [round(x) for x in new_b]:
                mismatch += 1
            period = (base_b[-1] - base_b[0]) / max(1, len(base_b) - 1)
            for b in new_b[1:-1]:
                rulers[classify(prof, int(round(b)), period)] += 1
            for b in base_b[1:-1]:
                rulers_base[classify(prof, int(round(b)), period)] += 1
            # 折线金标：新/旧 cells 的缝 vs 人折线
            if (pg, gc.col) in by_col_poly:
                x0p = int(round(min(c.x0 for c in r.cells))); x1p = int(round(max(c.x1 for c in r.cells)))
                old_cells = prod[gc.col].cells
                for it in by_col_poly[(pg, gc.col)]:
                    ex = it.expected
                    gseam = polyline_to_seam(ex["polyline"], x0p, x1p)
                    def eff(cells_, bounds_):
                        up = next((c for c in cells_ if c.kind == "char" and c.slot == ex.get("slot_above")), None)
                        if up is not None and getattr(up, "seam_bottom", None):
                            return list(up.seam_bottom)
                        yy = float(min(bounds_[1:-1], key=lambda b: abs(b - float(ex["y"]))))
                        return [int(round(yy))] * len(gseam)
                    poly_new.append(seam_deviation(eff(r.cells, new_b), gseam)[0])
                    poly_base.append(seam_deviation(eff(old_cells, base_b), gseam)[0])
            for it in by_col.get((pg, gc.col), []):
                ex = it.expected; bi = ex["bi"]
                if not (0 < bi < len(new_b) - 1):
                    continue
                g = float(ex["y"])
                if a.match == "nearest":
                    e_new = min(abs(b - g) for b in new_b[1:-1]); e_base = min(abs(b - g) for b in base_b[1:-1])
                else:
                    e_new, e_base = abs(new_b[bi] - g), abs(base_b[bi] - g)
                errs.append(e_new); errs_base.append(e_base)
                if a.diag_new and e_new > 20:
                    lo_i, hi_i = max(0, bi - 3), min(len(new_b), bi + 4)
                    print(f"   ✗ {it.id} {ex['verdict']} gold {int(g)} 现役 {int(base_b[bi])}(err {e_base:.0f}) 变体 err {e_new:.0f}")
                    print(f"       现役格线[{lo_i}:{hi_i}] {[int(x) for x in base_b[lo_i:hi_i]]}")
                    print(f"       变体格线[{lo_i}:{hi_i}] {[int(x) for x in new_b[lo_i:hi_i]]}  格类型 {[c.kind for c in r.cells][lo_i:hi_i]}")
                if a.diag and e_base > 10:
                    curve = RB.smooth_curve(prof.astype(np.float64) * img.shape[1])
                    vals = RB.find_valleys(curve, img.shape[1])
                    near = [(v, round(float(prof[v]), 3)) for v in vals if abs(v - g) <= 12]
                    diag_rows.append(dict(id=it.id, verdict=ex["verdict"], gold=int(g), base=int(base_b[bi]), new=int(new_b[bi]),
                                          ink_gold=round(float(prof[int(g)]), 3), ink_base=round(float(prof[int(base_b[bi])]), 3),
                                          valleys_near_gold=near, period=round(period, 1)))

    def stat(e):
        e = np.array(e) if e else np.zeros(0)
        if not e.size:
            return "n=0"
        return (f"n={len(e)} mean {e.mean():.1f} median {np.median(e):.1f} p90 {np.percentile(e, 90):.1f} "
                f"max {e.max():.0f} | ≤3px {100*(e<=3).mean():.1f}% ≤10px {100*(e<=10).mean():.1f}%")

    print(f"变体 {a.variant}  列 {n_cols}（无解 {n_fail}，与现役产物不一致 {mismatch}）")
    print("  金标误差 现役:", stat(errs_base))
    print("  金标误差 变体:", stat(errs))
    if poly_new:
        pn, pb = np.array(poly_new), np.array(poly_base)
        print(f"  折线金标 n={len(pn)} 最大偏差 现役: median {np.median(pb):.0f} p90 {np.percentile(pb,90):.0f} ≤6px {100*(pb<=6).mean():.1f}% >12px {int((pb>12).sum())}")
        print(f"  折线金标 n={len(pn)} 最大偏差 变体: median {np.median(pn):.0f} p90 {np.percentile(pn,90):.0f} ≤6px {100*(pn<=6).mean():.1f}% >12px {int((pn>12).sum())}")
    tot_b = sum(rulers_base.values()) or 1; tot_n = sum(rulers.values()) or 1
    print("  尺子 现役:", {k: f"{v} ({100*v/tot_b:.2f}%)" for k, v in sorted(rulers_base.items())})
    print("  尺子 变体:", {k: f"{v} ({100*v/tot_n:.2f}%)" for k, v in sorted(rulers.items())})
    if a.diag:
        for d in diag_rows:
            print("  ", d)
    if a.json:
        Path(a.json).write_text(json.dumps(dict(errs=errs, errs_base=errs_base, rulers=rulers, rulers_base=rulers_base),
                                           ensure_ascii=False), encoding="utf-8")
    if restore:
        restore()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
