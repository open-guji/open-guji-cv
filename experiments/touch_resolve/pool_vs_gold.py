# -*- coding: utf-8 -*-
"""选择器上限分析（现役产物 × 现役金标）：

每条金标 → 当前该切点的候选池 → 算每个候选与金标的像素误差 → 三类：
  A 选对：chosen 的误差 ≤ TOL
  B 选错但池里有对的：chosen 误差 > TOL，但 best 误差 ≤ TOL   ← 更好的选择器能救
  C 池里没有对的：best 误差 > TOL                             ← 要更好的候选，选择器救不了
再按 单候选/多候选、dis_unet 档、escalate 拆。

误差定义：候选缝（无缝=直线）与金标缝（无 polyline=直线 y）在窗口宽度上的 |dy| 的最大值。
用最大值不用均值：一处翻错一笔就是错，均值会被大片对的稀释。

    python pool_vs_gold.py [--book vol02] [--tol 6] [--rescale]
--rescale：金标 col_h 与现役不一致时按比例缩放 y 再比（回收漂移金标）。
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


def gold_seam(ex: dict, w: int, x_lo: int, scale: float) -> np.ndarray | None:
    """金标 → 每列一个 y（窗口宽 w，窗口起点 x_lo）。"""
    pl = ex.get("polyline")
    if pl:
        pts = np.asarray(pl, dtype=float)
        if pts.ndim == 2 and pts.shape[1] == 2:          # [[x,y],...]
            xs, ys = pts[:, 0] - x_lo, pts[:, 1] * scale
            order = np.argsort(xs)
            return np.interp(np.arange(w), xs[order], ys[order])
        if pts.ndim == 1:                                  # 每列一个 y
            ys = pts * scale
            if len(ys) == w:
                return ys
            return np.interp(np.linspace(0, len(ys) - 1, w), np.arange(len(ys)), ys)
    y = ex.get("y")
    if y is None:
        return None
    return np.full(w, float(y) * scale)


def cand_seam(cp, cand, w: int) -> np.ndarray:
    if cand.y is None:
        return np.full(w, float(cp.y))
    ys = np.asarray(cand.y, dtype=float)
    if len(ys) == w:
        return ys
    return np.interp(np.linspace(0, len(ys) - 1, w), np.arange(len(ys)), ys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None)
    ap.add_argument("--tol", type=float, default=6.0)
    ap.add_argument("--rescale", action="store_true")
    ap.add_argument("--dump", default=None, help="逐条结果 json")
    a = ap.parse_args()

    st, ic = ProductStore(), ImageCache()
    items = [i for i in verdict_store().list(SHARD)
             if getattr(i, "status", "active") == "active"
             and (a.book is None or str(i.anchor.book) == a.book)]
    print(f"金标 active {len(items)}（book={a.book or 'all'}）")

    cells_cache, img_cache = {}, {}
    rows = []
    skip = Counter()
    for it in items:
        b, pg, col, slot = str(it.anchor.book), it.anchor.page, it.anchor.col, it.anchor.slot
        ex = it.expected or {}
        if pg is None or col is None or slot is None:
            skip["无锚点"] += 1
            continue
        key = (b, pg)
        if key not in cells_cache:
            cells_cache[key] = st.read(b, "row_segment", page_key(pg), "cells")
        cells = cells_cache[key]
        cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None)
        if cc is None:
            skip["无该列产物"] += 1
            continue
        ck = (b, pg, col)
        if ck not in img_cache:
            p = ic.get(b, "column_image", column_key(pg, col))
            im = cv2.imread(str(p), 0) if p else None
            img_cache[ck] = None if im is None else im.shape[0]
        h = img_cache[ck]
        gh = ex.get("col_h")
        scale = 1.0
        if h is None or gh is None:
            skip["无列高"] += 1
            continue
        if abs(h - int(gh)) > 2:
            if not a.rescale:
                skip["漂移(未回收)"] += 1
                continue
            scale = h / float(gh)
        cp = next((x for x in (cc.cut_candidates or []) if x.slot_above == slot), None)
        x_lo, x_hi = (int(round(v)) for v in (cc.content_x or (0, 0)))
        w = x_hi - x_lo
        if w <= 0:
            skip["无窗宽"] += 1
            continue
        gs = gold_seam(ex, w, x_lo, scale)
        if gs is None:
            skip["金标无几何"] += 1
            continue
        if cp is None or not cp.candidates:
            # 不是多候选切点：现役就是格线直线。用 cells 边界当唯一候选。
            cm = {c.slot: c for c in cc.cells if c.sub is None}
            up = cm.get(slot)
            if up is None:
                skip["无格"] += 1
                continue
            seam = np.full(w, float(getattr(up, "y1", np.nan)))
            if not np.isfinite(seam).all():
                skip["无格线"] += 1
                continue
            e = float(np.max(np.abs(seam - gs)))
            rows.append({"id": f"{b}:{pg}:{col}:{slot}", "book": b, "verdict": ex.get("verdict"),
                         "n_cand": 1, "chosen_err": e, "best_err": e, "best_i": 0, "chosen": 0,
                         "chosen_kind": "straight", "chosen_by": "rule", "dis": None,
                         "esc": False, "scale": scale})
            continue
        errs = [float(np.max(np.abs(cand_seam(cp, c, w) - gs))) for c in cp.candidates]
        ch = cp.chosen if cp.chosen is not None else 0
        bi = int(np.argmin(errs))
        rows.append({"id": f"{b}:{pg}:{col}:{slot}", "book": b, "verdict": ex.get("verdict"),
                     "n_cand": len(cp.candidates), "chosen_err": errs[ch], "best_err": errs[bi],
                     "best_i": bi, "chosen": ch, "chosen_kind": cp.candidates[ch].kind,
                     "best_kind": cp.candidates[bi].kind, "chosen_by": cp.chosen_by,
                     "dis": cp.candidates[ch].dis_unet, "esc": bool(cp.escalate), "scale": scale,
                     "cands": [(c.kind, round(e, 1), c.dis_unet) for c, e in zip(cp.candidates, errs)]})

    print("跳过:", dict(skip))
    print(f"可比 {len(rows)}")
    T = a.tol

    def cls(r):
        if r["chosen_err"] <= T:
            return "A 选对"
        if r["best_err"] <= T:
            return "B 选错·池里有对的"
        return "C 池里没对的"

    for r in rows:
        r["cls"] = cls(r)

    def report(title, sub):
        if not sub:
            return
        c = Counter(r["cls"] for r in sub)
        n = len(sub)
        print(f"\n[{title}] n={n}  " + "  ".join(f"{k} {v} ({v/n:.1%})" for k, v in sorted(c.items())))

    report("全部", rows)
    report("单候选", [r for r in rows if r["n_cand"] == 1])
    multi = [r for r in rows if r["n_cand"] >= 2]
    report("多候选", multi)
    report("多候选·人裁过(chosen_by=human)", [r for r in multi if r["chosen_by"] == "human"])
    mach = [r for r in multi if r["chosen_by"] != "human"]
    report("多候选·机器选(非 human)", mach)
    report("  其中 escalate", [r for r in mach if r["esc"]])
    report("  其中 dis>=60 未升级", [r for r in mach if not r["esc"] and (r["dis"] or 0) >= 60])
    report("  其中 dis<60", [r for r in mach if not r["esc"] and (r["dis"] or 0) < 60])

    # B 类：选择器能救的——看现役选的是什么、对的是什么
    B = [r for r in mach if r["cls"].startswith("B")]
    print(f"\n=== B 类（机器选错、池里有对的）{len(B)} 条：chosen_kind → best_kind ===")
    print(Counter((r["chosen_kind"], r.get("best_kind")) for r in B).most_common(12))
    C = [r for r in mach if r["cls"].startswith("C")]
    print(f"\n=== C 类（池里没对的）{len(C)} 条：best_err 分布 ===")
    print(Counter(("<15" if r["best_err"] < 15 else "15-30" if r["best_err"] < 30 else "30-60" if r["best_err"] < 60 else ">=60") for r in C))
    for r in sorted(C, key=lambda r: -r["best_err"])[:10]:
        print(f"   {r['id']:18s} best={r['best_err']:5.1f} chosen={r['chosen_err']:5.1f} n={r['n_cand']} dis={r['dis']} esc={r['esc']} v={r['verdict']}")

    if a.dump:
        json.dump(rows, open(a.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("dump ->", a.dump)


main()
