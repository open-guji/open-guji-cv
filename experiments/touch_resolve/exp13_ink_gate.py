# -*- coding: utf-8 -*-
"""实验十三：用「直线上的墨」区分「干净格线（留直线）」与「真粘连（用 U-Net 缝）」。

实验十二看到：现役选法赢在金标 ok 组（直线本来就对），U-Net 缝赢在 moved 组（要改）。
两者互补，理想切换可到 ~43/62。缺的是一个不看金标就能分组的信号。
候选信号：直线 y 上的墨占比 ink_line（R2s 尺子就是靠它分「真粘连」的）。

策略 P(τ, turn)：ink_line < τ → 选直线；否则 → 选 U-Net 缝（刚度 turn）。
另比：P'(τ)：ink_line < τ → 选直线；否则 → 保持现役选法。（只用信号救 ok 组，不动 moved 组）

    python exp13_ink_gate.py --pvg pvg.json
"""
import argparse
import json
import statistics as S

import cv2
import numpy as np

from open_guji_cv.core.spec import column_key
from open_guji_cv.core.step import page_key
from open_guji_cv.eval.touching import SHARD
from open_guji_cv.feedback.consumers import verdict_store
from open_guji_cv.products import kinds as _k  # noqa: F401
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.utils.cut_select import INK_TH, get_judge, guided_seam_from_owner


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


def seam_err(sm, gs, w):
    sm = np.asarray(sm, float)
    if len(sm) != w:
        sm = np.interp(np.linspace(0, len(sm) - 1, w), np.arange(len(sm)), sm)
    return float(np.max(np.abs(sm - gs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pvg", required=True)
    ap.add_argument("--turn", type=float, default=10.0)
    ap.add_argument("--tol", type=float, default=6.0)
    a = ap.parse_args()
    rows = json.load(open(a.pvg, encoding="utf-8"))
    pt = {(str(i.anchor.book), int(i.anchor.page)): (i.expected or {}).get("page_type")
          for i in verdict_store().list("page-type", legacy=False) if i.anchor.page is not None}
    sel = [r for r in rows if r["n_cand"] >= 2 and r["book"] != "vol03"
           and pt.get((r["book"], int(r["id"].split(":")[1]))) == "body"
           and r["verdict"] != "overlap"]        # overlap=切在哪都伤字，eval 也不计

    gold = {f"{i.anchor.book}:{i.anchor.page}:{i.anchor.col}:{i.anchor.slot}": (i.expected or {})
            for i in verdict_store().list(SHARD)}
    st, ic = ProductStore(), ImageCache()
    judge = get_judge()

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
        img = cv2.imread(str(ic.get(b, "column_image", column_key(pg, col))), 0)
        x0, x1 = (int(round(v)) for v in cc.content_x)
        y0, y1 = int(max(0, up.y0)), int(min(img.shape[0], dn.y1))
        w = x1 - x0
        win = img[y0:y1, x0:x1]
        gs = gold_seam(gold[r["id"]], w, x0)
        if gs is None:
            continue
        ink = (win < INK_TH)
        yl = int(round(cp.y)) - y0
        yl = min(max(yl, 0), win.shape[0] - 1)
        # 直线上的墨：本行 ±1 行的最大墨占比（防线正好落在笔画边缘的 1px 空隙）
        band = ink[max(0, yl - 1):yl + 2, :]
        ink_line = float(band.mean(axis=1).max())
        # 直线附近 ±6 行的最小墨（有没有谷）
        nb = ink[max(0, yl - 6):yl + 7, :].mean(axis=1)
        ink_valley = float(nb.min())
        # 直线误差、现役误差、U-Net 缝误差
        e_straight = seam_err(np.full(w, float(cp.y)), gs, w)
        _, ou, _ = judge.owner(win, INK_TH)
        sm = guided_seam_from_owner(ou, yl, turn=a.turn)
        e_unet = None if sm is None else seam_err(np.asarray(sm) + y0, gs, w)
        per.append({"id": r["id"], "v": r["verdict"], "ink_line": ink_line, "ink_valley": ink_valley,
                    "e_cur": r["chosen_err"], "e_str": e_straight, "e_unet": e_unet,
                    "cur_kind": r["chosen_kind"]})
    print(f"可算 {len(per)}")
    T = a.tol

    print("\n=== 信号分布：ink_line 按金标组 ===")
    for v in ("ok", "moved", "cand"):
        g = [p for p in per if p["v"] == v]
        if g:
            il = sorted(p["ink_line"] for p in g)
            print(f"  {v:5s} n={len(g):2d}  ink_line 中位 {S.median(il):.3f}  分位 25/75 {il[len(il)//4]:.3f}/{il[3*len(il)//4]:.3f}  最小 {il[0]:.3f} 最大 {il[-1]:.3f}")
    print("  ink_valley 同上：")
    for v in ("ok", "moved", "cand"):
        g = [p for p in per if p["v"] == v]
        if g:
            iv = sorted(p["ink_valley"] for p in g)
            print(f"  {v:5s} 中位 {S.median(iv):.3f}  25/75 {iv[len(iv)//4]:.3f}/{iv[3*len(iv)//4]:.3f}")

    print(f"\n=== 策略扫描（≤{T:.0f}px 命中）  现役 {sum(1 for p in per if p['e_cur']<=T)}/{len(per)} ===")
    print(f"{'τ':>6s} | {'P: 直线/否则U-Net':>18s} | {'P′: 直线/否则现役':>18s} | {'直线组n':>6s} {'其中ok':>5s}")
    for tau in (0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2):
        hitP = hitP2 = 0
        n_str = n_str_ok = 0
        for p in per:
            if p["ink_line"] <= tau:
                e = p["e_str"]
                n_str += 1
                n_str_ok += p["v"] == "ok"
                hitP += e <= T
                hitP2 += e <= T
            else:
                hitP += (p["e_unet"] is not None and p["e_unet"] <= T)
                hitP2 += p["e_cur"] <= T
        print(f"{tau:6.2f} | {hitP:6d}/{len(per):<10d} | {hitP2:6d}/{len(per):<10d} | {n_str:6d} {n_str_ok:5d}")

    print("\n=== 上限：每条取 min(直线, U-Net缝) 的命中 ===")
    print(f"  {sum(1 for p in per if min(p['e_str'], p['e_unet'] or 1e9) <= T)}/{len(per)}")
    print("=== 上限：min(直线, 现役, U-Net缝) ===")
    print(f"  {sum(1 for p in per if min(p['e_str'], p['e_cur'], p['e_unet'] or 1e9) <= T)}/{len(per)}")

    # 逐条：ink_line 与三种误差
    print("\n=== 逐条（按 ink_line 升序） ===")
    for p in sorted(per, key=lambda p: p["ink_line"]):
        eu = "  -  " if p["e_unet"] is None else f"{p['e_unet']:5.1f}"
        print(f"  {p['id']:18s} v={p['v']:5s} ink={p['ink_line']:.3f} valley={p['ink_valley']:.3f} | 直线 {p['e_str']:5.1f} 现役 {p['e_cur']:5.1f}({p['cur_kind'][:6]}) U-Net {eu}")


main()
