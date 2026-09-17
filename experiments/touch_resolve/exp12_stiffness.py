# -*- coding: utf-8 -*-
"""实验十二：U-Net 引导缝的**刚度**。

现役 `guided_seam_from_owner(turn=0.02)`：代价 = 错归属像素数 + 0.02×纵移。移 10 行只花 0.2，
不到一个像素——一个 U-Net 噪声像素就值得绕 50 行。这解释了为什么在干净格线上（金标 ok）
U-Net 缝会乱抖、比直线差；而在真粘连（金标 moved）上它能找对边界（省几百像素）。

扫 turn ∈ {0.02, 0.1, 0.3, 1, 3, 10} × band ∈ {45, 30}，对**现役产物 × col_h 一致的正文页多候选金标**：
  - 新 unet_seam 与金标的最大 |dy|
  - 若「池里有 unet_seam 就选它」，与现役选法比：变好/变差/持平、≤6px 命中率
  - 按金标 verdict 拆（ok=直线本来就对；moved/cand=要改）

    python exp12_stiffness.py --pvg pvg.json
"""
import argparse
import json
import statistics as S
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
from open_guji_cv.utils.cut_select import GUIDED_BAND, INK_TH, get_judge, guided_seam_from_owner


def gold_seam(ex, w, x_lo):
    pl = ex.get("polyline")
    if pl:
        pts = np.asarray(pl, dtype=float)
        if pts.ndim == 2 and pts.shape[1] == 2:
            xs, ys = pts[:, 0] - x_lo, pts[:, 1]
            o = np.argsort(xs)
            return np.interp(np.arange(w), xs[o], ys[o])
        if pts.ndim == 1:
            return np.interp(np.linspace(0, len(pts) - 1, w), np.arange(len(pts)), pts)
    y = ex.get("y")
    return None if y is None else np.full(w, float(y))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pvg", required=True)
    ap.add_argument("--turns", default="0.02,0.1,0.3,1,3,10")
    ap.add_argument("--bands", default="45,30")
    ap.add_argument("--tol", type=float, default=6.0)
    a = ap.parse_args()
    turns = [float(t) for t in a.turns.split(",")]
    bands = [int(b) for b in a.bands.split(",")]

    rows = json.load(open(a.pvg, encoding="utf-8"))
    pt_items = verdict_store().list("page-type", legacy=False)
    pt = {(str(i.anchor.book), int(i.anchor.page)): (i.expected or {}).get("page_type")
          for i in pt_items if i.anchor.page is not None}
    sel = [r for r in rows if r["n_cand"] >= 2 and r["book"] != "vol03"
           and pt.get((r["book"], int(r["id"].split(":")[1]))) == "body"]
    print(f"正文页多候选金标 {len(sel)}")

    gold = {f"{i.anchor.book}:{i.anchor.page}:{i.anchor.col}:{i.anchor.slot}": (i.expected or {})
            for i in verdict_store().list(SHARD)}
    st, ic = ProductStore(), ImageCache()
    judge = get_judge()
    assert judge is not None, "U-Net 裁判加载失败"

    # 每条：算一次 owner，再对每个 (turn, band) 出缝
    per = []
    for r in sel:
        b, pg, col, slot = r["id"].split(":")
        pg, col, slot = int(pg), int(col), int(slot)
        cells = st.read(b, "row_segment", page_key(pg), "cells")
        cc = next((c for c in cells.columns if c.col == col), None)
        cm = {c.slot: c for c in cc.cells if c.sub is None}
        up, dn = cm.get(slot), cm.get(slot + 1)
        cp = next((x for x in (cc.cut_candidates or []) if x.slot_above == slot), None)
        if up is None or dn is None or cp is None:
            continue
        path = ic.get(b, "column_image", column_key(pg, col))
        img = cv2.imread(str(path), 0)
        x0, x1 = (int(round(v)) for v in cc.content_x)
        y0, y1 = int(max(0, up.y0)), int(min(img.shape[0], dn.y1))
        w = x1 - x0
        win = img[y0:y1, x0:x1]
        gs = gold_seam(gold[r["id"]], w, x0)
        if gs is None:
            continue
        _, ou, _ = judge.owner(win, INK_TH)
        yl = int(round(cp.y)) - y0
        errs = {}
        for band in bands:
            for t in turns:
                sm = guided_seam_from_owner(ou, yl, band=band, turn=t)
                if sm is None:
                    errs[(band, t)] = None
                    continue
                sm = np.asarray(sm, float) + y0
                if len(sm) != w:
                    sm = np.interp(np.linspace(0, len(sm) - 1, w), np.arange(len(sm)), sm)
                errs[(band, t)] = float(np.max(np.abs(sm - gs)))
        per.append({"id": r["id"], "verdict": r["verdict"], "chosen_err": r["chosen_err"],
                    "best_err": r["best_err"], "errs": errs})
    print(f"可算 {len(per)}")

    T = a.tol
    print(f"\n{'band':>4s} {'turn':>6s} | {'新缝≤6':>7s} {'新缝中位':>7s} | {'换选:好/差/平':>14s} | {'ok组 新缝≤6':>11s} {'moved组 新缝≤6':>13s} | {'现役≤6':>6s}")
    base_hit = sum(1 for p in per if p["chosen_err"] <= T)
    for band in bands:
        for t in turns:
            es = [(p, p["errs"][(band, t)]) for p in per if p["errs"].get((band, t)) is not None]
            hit = sum(1 for p, e in es if e <= T)
            med = S.median([e for _, e in es])
            win = sum(1 for p, e in es if e < p["chosen_err"] - 1)
            lose = sum(1 for p, e in es if e > p["chosen_err"] + 1)
            tie = len(es) - win - lose
            ok_g = [(p, e) for p, e in es if p["verdict"] == "ok"]
            mv_g = [(p, e) for p, e in es if p["verdict"] in ("moved", "cand", "seam_ok")]
            ok_hit = f"{sum(1 for _, e in ok_g if e <= T)}/{len(ok_g)}"
            mv_hit = f"{sum(1 for _, e in mv_g if e <= T)}/{len(mv_g)}"
            print(f"{band:4d} {t:6.2f} | {hit:3d}/{len(es):<3d} {med:7.1f} | {win:4d}/{lose:<4d}/{tie:<4d} | {ok_hit:>11s} {mv_hit:>13s} | {base_hit:3d}/{len(per)}")

    # 最优组合下，逐条对照（只列变差的）
    best = max(((band, t) for band in bands for t in turns),
               key=lambda k: sum(1 for p in per if (p["errs"].get(k) or 1e9) <= T))
    print(f"\n最优 (band,turn)={best}：变差的条目（现役→新缝）")
    for p in per:
        e = p["errs"].get(best)
        if e is not None and e > p["chosen_err"] + 1:
            print(f"  {p['id']:18s} {p['chosen_err']:5.1f} → {e:5.1f}  v={p['verdict']}")
    print(f"\n{best} 下仍 >{T}px 的（新缝也救不了）：")
    for p in per:
        e = p["errs"].get(best)
        if e is not None and e > T:
            print(f"  {p['id']:18s} 新缝 {e:5.1f}  现役 {p['chosen_err']:5.1f}  池最好 {p['best_err']:5.1f}  v={p['verdict']}")


main()
