# -*- coding: utf-8 -*-
"""实验十七：按实验十六的结论恢复漂移金标，并验证恢复出来的金标「行为正常」。

恢复规则（每条金标各自的锚点 d = boundaries[bi] − y_old）：
  |d| ≤ 3  → 恒等，金标坐标原样用
  |d| > 3  → 把 y 和 polyline 整体平移 d（列顶动了那几列）
x 方向：polyline 的 x 是列内局部坐标，检查其范围是否落在当前 content_x 宽度内。

验证：恢复后的 vol01 金标跑一遍 A/B/C（同 pool_vs_gold 口径），与「本来就匹配」的那批比——
两批的选对率、B/C 比例若接近，说明恢复没引入偏差；若恢复批明显更差，说明平移假设有问题。

    python exp17_recover_gold.py --book vol01 [--tol 6] [--dump recovered.json]
"""
import argparse
import json
from collections import Counter, defaultdict

import cv2
import numpy as np

from open_guji_cv.core.spec import column_key
from open_guji_cv.core.step import page_key
from open_guji_cv.eval.touching import SHARD
from open_guji_cv.feedback.consumers import verdict_store
from open_guji_cv.products import kinds as _k  # noqa: F401
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

SNAP = 3.0


def gold_seam(ex, w, x_lo, dy):
    pl = ex.get("polyline")
    if pl:
        pts = np.asarray(pl, dtype=float)
        if pts.ndim == 2 and pts.shape[1] == 2:
            xs, ys = pts[:, 0] - x_lo, pts[:, 1] + dy
            o = np.argsort(xs)
            return np.interp(np.arange(w), xs[o], ys[o]), (float(pts[:, 0].min()), float(pts[:, 0].max()))
    y = ex.get("y")
    return (None if y is None else np.full(w, float(y) + dy)), None


def cand_seam(cp, c, w):
    if c.y is None:
        return np.full(w, float(cp.y))
    ys = np.asarray(c.y, float)
    return ys if len(ys) == w else np.interp(np.linspace(0, len(ys) - 1, w), np.arange(len(ys)), ys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--tol", type=float, default=6.0)
    ap.add_argument("--dump", default=None)
    a = ap.parse_args()
    st, ic = ProductStore(), ImageCache()
    pt = {(str(i.anchor.book), int(i.anchor.page)): (i.expected or {}).get("page_type")
          for i in verdict_store().list("page-type", legacy=False) if i.anchor.page is not None}
    items = [i for i in verdict_store().list(SHARD)
             if str(i.anchor.book) == a.book and getattr(i, "status", "active") == "active"]

    rows, skip = [], Counter()
    cc_cache, h_cache = {}, {}
    xrange_bad = 0
    for it in items:
        ex = it.expected or {}
        pg, col, slot = it.anchor.page, it.anchor.col, it.anchor.slot
        bi, yo, ho = ex.get("bi"), ex.get("y_old"), ex.get("col_h")
        if None in (pg, col, slot, bi, yo, ho):
            skip["缺字段"] += 1
            continue
        if pg not in cc_cache:
            cc_cache[pg] = st.read(a.book, "row_segment", page_key(pg), "cells")
        cells = cc_cache[pg]
        cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None)
        if cc is None:
            skip["无列产物"] += 1
            continue
        k = (pg, col)
        if k not in h_cache:
            p = ic.get(a.book, "column_image", column_key(pg, col))
            im = cv2.imread(str(p), 0) if p else None
            h_cache[k] = None if im is None else im.shape[0]
        hn = h_cache[k]
        if hn is None or not (0 <= int(bi) < len(cc.boundaries)):
            skip["无列图/bi越界"] += 1
            continue
        drifted = abs(hn - int(ho)) > 2
        d = float(cc.boundaries[int(bi)]) - float(yo)
        dy = 0.0 if abs(d) <= SNAP else d
        mode = "匹配" if not drifted else ("恒等" if abs(d) <= SNAP else "平移")
        x_lo, x_hi = (int(round(v)) for v in (cc.content_x or (0, 0)))
        w = x_hi - x_lo
        if w <= 0:
            skip["无窗宽"] += 1
            continue
        gs, xr = gold_seam(ex, w, x_lo, dy)
        if gs is None:
            skip["金标无几何"] += 1
            continue
        if xr is not None and (xr[0] < x_lo - 6 or xr[1] > x_hi + 6):
            xrange_bad += 1
        cp = next((x for x in (cc.cut_candidates or []) if x.slot_above == slot), None)
        if cp is None or not cp.candidates:
            cm = {c.slot: c for c in cc.cells if c.sub is None}
            up = cm.get(slot)
            if up is None:
                skip["无格"] += 1
                continue
            e = float(np.max(np.abs(np.full(w, float(up.y1)) - gs)))
            rows.append({"id": f"{a.book}:{pg}:{col}:{slot}", "mode": mode, "d": d, "verdict": ex.get("verdict"),
                         "n_cand": 1, "chosen_err": e, "best_err": e, "chosen_by": "rule",
                         "page_type": pt.get((a.book, pg))})
            continue
        errs = [float(np.max(np.abs(cand_seam(cp, c, w) - gs))) for c in cp.candidates]
        ch = cp.chosen if cp.chosen is not None else 0
        bi_ = int(np.argmin(errs))
        rows.append({"id": f"{a.book}:{pg}:{col}:{slot}", "mode": mode, "d": d, "verdict": ex.get("verdict"),
                     "n_cand": len(cp.candidates), "chosen_err": errs[ch], "best_err": errs[bi_],
                     "chosen_kind": cp.candidates[ch].kind, "best_kind": cp.candidates[bi_].kind,
                     "chosen_by": cp.chosen_by, "dis": cp.candidates[ch].dis_unet, "esc": bool(cp.escalate),
                     "page_type": pt.get((a.book, pg)),
                     "cands": [(c.kind, round(e, 1), c.dis_unet) for c, e in zip(cp.candidates, errs)]})

    T = a.tol
    print(f"{a.book}：金标 {len(items)}，可比 {len(rows)}，跳过 {dict(skip)}，polyline x 超出列宽 {xrange_bad}")
    print("恢复方式：", dict(Counter(r["mode"] for r in rows)))
    big = [r for r in rows if r["mode"] == "平移"]
    if big:
        print(f"  平移量 |d|：中位 {np.median([abs(r['d']) for r in big]):.0f}  最大 {max(abs(r['d']) for r in big):.0f}；涉及页：{sorted({int(r['id'].split(':')[1]) for r in big})[:20]}")

    def cls(r):
        if r["chosen_err"] <= T:
            return "A"
        return "B" if r["best_err"] <= T else "C"
    for r in rows:
        r["cls"] = cls(r)

    def rep(title, sub):
        if not sub:
            print(f"[{title}] n=0")
            return
        c = Counter(r["cls"] for r in sub)
        n = len(sub)
        print(f"[{title:28s}] n={n:4d}  A {c['A']:4d} ({c['A']/n:5.1%})  B {c['B']:3d} ({c['B']/n:5.1%})  C {c['C']:3d} ({c['C']/n:5.1%})")

    print("\n=== 恢复批 vs 匹配批：行为是否一致 ===")
    for mode in ("匹配", "恒等", "平移"):
        sub = [r for r in rows if r["mode"] == mode]
        rep(f"{mode}·全部", sub)
        rep(f"{mode}·单候选", [r for r in sub if r["n_cand"] == 1])
        rep(f"{mode}·单候选·非human", [r for r in sub if r["n_cand"] == 1 and r["chosen_by"] != "human"])
        rep(f"{mode}·多候选", [r for r in sub if r["n_cand"] >= 2])
    print()
    body_multi = [r for r in rows if r["n_cand"] >= 2 and r["page_type"] == "body"]
    rep("全部·正文·多候选（机器独立选）", body_multi)
    rep("  其中原本匹配", [r for r in body_multi if r["mode"] == "匹配"])
    rep("  其中恢复回来", [r for r in body_multi if r["mode"] != "匹配"])
    print("\n正文多候选按 verdict：", dict(Counter(r["verdict"] for r in body_multi)))
    if a.dump:
        json.dump(rows, open(a.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("dump ->", a.dump)


main()
