# -*- coding: utf-8 -*-
"""量真实粘连点的几何：按人工金标缝分上下后，B 的墨顶行 − A 的墨底行 − 1（g，负 = 纵向交错），
以及直线能达到的最优归属一致率——用来校准合成器的 GAP_MIX，并回答「缝表达不了的占多少」。

    python scripts/touch_resolve/gold_geometry.py
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
import numpy as np
from common import INK_TH, Loader, OUT_ROOT, jdump, seam_gold, side_masks, window


def main() -> int:
    L = Loader()
    rows = []
    for it in L.gold_items():
        c, _ = L.resolve(it)
        if c is None:
            continue
        img = L.image_of(c)
        if img is None:
            continue
        win, y0, _ = window(c, img)
        ink = win < INK_TH
        above, below = side_masks(win.shape, seam_gold(c), y0)
        A = ink & above; B = ink & below
        ra = np.nonzero(A.any(axis=1))[0]; rb = np.nonzero(B.any(axis=1))[0]
        if ra.size == 0 or rb.size == 0:
            continue
        g = int(rb.min()) - int(ra.max()) - 1
        # 直线最优一致率
        r1 = A.sum(axis=1); r2 = B.sum(axis=1); c1 = np.cumsum(r1); c2 = np.cumsum(r2); nv = r1.sum() + r2.sum()
        best = max((c1[y - 1] + (c2[-1] - c2[y - 1])) / nv for y in range(1, win.shape[0]))
        # 交错列数：某列 x 上 A 的最低墨低于 B 的最高墨
        inter = 0
        for x in range(win.shape[1]):
            ca = np.nonzero(A[:, x])[0]; cb = np.nonzero(B[:, x])[0]
            if ca.size and cb.size and ca.max() > cb.min():
                inter += 1
        rows.append(dict(id=c.id, verdict=c.verdict, poly=bool(c.gold_poly), g=g, straight_best=float(best), inter_cols=inter,
                         w=win.shape[1]))
    by_v = defaultdict(list)
    for r in rows:
        by_v[r["verdict"]].append(r)
    print(f"n={len(rows)}")
    print("verdict      n   g<0    g<-5   g<-10  median_g  直线最优<0.98  <0.95  交错列>0")
    for v, rs in sorted(by_v.items(), key=lambda kv: -len(kv[1])):
        gs = np.array([r["g"] for r in rs]); sb = np.array([r["straight_best"] for r in rs]); ic = np.array([r["inter_cols"] for r in rs])
        print(f"{v:10s} {len(rs):4d}  {(gs<0).mean():5.1%} {(gs<-5).mean():5.1%} {(gs<-10).mean():5.1%}   {np.median(gs):5.0f}    "
              f"{(sb<0.98).mean():6.1%}   {(sb<0.95).mean():5.1%}   {(ic>0).mean():5.1%}")
    gs = np.array([r["g"] for r in rows])
    hist = Counter(int(np.clip(g, -30, 10)) // 3 * 3 for g in gs)
    print("g 直方（按 3px 桶）:", dict(sorted(hist.items())))
    jdump(rows, OUT_ROOT / "gold_geometry.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
