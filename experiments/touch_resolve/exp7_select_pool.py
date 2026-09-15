# -*- coding: utf-8 -*-
"""实验七：候选池选择器——U-Net 当裁判，在几何候选（直线 / 窄走廊 / 宽走廊）里挑一条。

    python experiments/touch_resolve/exp7_select_pool.py [--cc-max 400]

实验六的结论：候选池 {直线, 窄, 宽} 的上限大块错 0.7%，加 U-Net 归属 0.0%；现役缝 5.2% 的大块错几乎全是**选错了候选**。
这里不让 U-Net 直接出归属（它边界毛、≤20px 只有 77%），而是让它**给每条几何候选打分**：
  agree_w(cand) = Σ_ink conf · [owner_cand == owner_unet] / Σ_ink conf     （U-Net 置信加权的一致率）
选法：
  S1  几何候选里 agree_w 最高者（平手取现役缝）；
  S2τ S1 之后若最高 agree_w < τ（几何候选都不像 U-Net 的意思，典型是三条缝全走错了白缝）→ 改用 U-Net 归属；
  S3δ 只有当最优候选比现役缝的 agree_w 高出 ≥ δ 才换（保守版）；
  参照：现役缝 / U-Net / 实验六规则 / 候选池上限 / 全池上限。
尺子同前：err_px、blob≥60、blob≥150。产出 out/exp7/per_case.json（逐候选特征，留给学习型选择器）、summary.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, Loader, OUT_ROOT, jdump, seam_chosen, seam_gold, seams_candidates, window  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from exp6_selector import unet_owner  # noqa: E402
from templates import owner_from_seam  # noqa: E402
from train_partition_unet_v2 import MODEL_DIR, build_model  # noqa: E402


def dis_blob(a: np.ndarray, b: np.ndarray, W: np.ndarray) -> int:
    m = (W > 0) & (a != b)
    if not m.any():
        return 0
    _, _, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    return int(st[1:, cv2.CC_STAT_AREA].max())


def main() -> int:
    import torch
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc-max", type=int, default=400)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev)
    net.load_state_dict(torch.load(MODEL_DIR / "partition_unet_v2.pt", map_location=dev)["state"])
    net.eval()
    L = Loader()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    out = OUT_ROOT / "exp7"
    out.mkdir(parents=True, exist_ok=True)
    per = []
    for it in L.gold_items(books=a.books.split(",")):
        if it.id not in frame_ok:
            continue
        c, _ = L.resolve(it)
        if c is None or L.image_of(c) is None:
            continue
        rk = (exp1.get(c.id) or {}).get("rank", {}).get("gold", {})
        label_ok = bool(rk.get("fused_above") and rk["fused_above"] <= 5 and rk.get("fused_below") and rk["fused_below"] <= 5)
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        W, ou, conf = unet_owner(net, dev, win, a.cc_max)
        ink = W > 0
        cw = conf[ink]
        og = owner_from_seam(W, seam_gold(c) - y0)
        sc = seam_chosen(c)
        oc = owner_from_seam(W, sc - y0)
        straight_y = c.straight_y
        cands = []
        seen = []
        for kind, seam in seams_candidates(c):
            key = tuple(int(v) for v in seam)
            if key in seen:
                continue
            seen.append(key)
            o = owner_from_seam(W, seam - y0)
            n, blob = err_stats(o, og)
            eq = (o[ink] == ou[ink])
            h = win.shape[0]
            ys = np.clip(seam - y0, 0, h - 1)
            seam_ink = int(W[ys, np.arange(len(seam))].sum())
            cands.append({"kind": kind, "is_chosen": bool(np.array_equal(seam, sc)),
                          "err": {"px": n, "blob": blob},
                          "agree": round(float(eq.mean()), 4) if eq.size else 1.0,
                          "agree_w": round(float((cw * eq).sum() / max(cw.sum(), 1e-6)), 4) if eq.size else 1.0,
                          "dis_unet": dis_blob(o, ou, W), "dis_chosen": dis_blob(o, oc, W),
                          "seam_ink": seam_ink, "dev_max": int(np.abs(seam - straight_y).max())})
        if not any(cd["is_chosen"] for cd in cands):        # 现役缝不在候选表里（老产物）也放进池
            n, blob = err_stats(oc, og)
            eq = (oc[ink] == ou[ink])
            cands.append({"kind": "chosen", "is_chosen": True, "err": {"px": n, "blob": blob},
                          "agree": round(float(eq.mean()), 4), "agree_w": round(float((cw * eq).sum() / max(cw.sum(), 1e-6)), 4),
                          "dis_unet": dis_blob(oc, ou, W), "dis_chosen": 0, "seam_ink": -1,
                          "dev_max": int(np.abs(sc - straight_y).max())})
        n_u, blob_u = err_stats(ou, og)
        per.append({"id": c.id, "verdict": c.verdict, "book": c.book, "page": c.page, "label_ok": label_ok,
                    "n_cand": len(cands), "cands": cands, "unet": {"px": n_u, "blob": blob_u},
                    "conf_mean": round(float(cw.mean()), 4) if cw.size else None})
    jdump(per, out / "per_case.json")

    def agg(rows, get):
        px = np.array([get(r)["px"] for r in rows])
        bl = np.array([get(r)["blob"] for r in rows])
        if not px.size:
            return None
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
                "blob_ge150": round(float((bl >= 150).mean()), 4)}

    def chosen(r):
        return next(cd for cd in r["cands"] if cd["is_chosen"])["err"]

    def s1(r):
        best = max(r["cands"], key=lambda cd: (cd["agree_w"], cd["is_chosen"]))
        return best

    def S1(r):
        return s1(r)["err"]

    def S2(tau):
        def f(r):
            b = s1(r)
            return r["unet"] if b["agree_w"] < tau else b["err"]
        return f

    def S3(delta):
        def f(r):
            ch = next(cd for cd in r["cands"] if cd["is_chosen"])
            b = s1(r)
            return b["err"] if b["agree_w"] - ch["agree_w"] >= delta else ch["err"]
        return f

    def S23(tau, delta):
        def f(r):
            ch = next(cd for cd in r["cands"] if cd["is_chosen"])
            b = s1(r)
            pick = b["err"] if b["agree_w"] - ch["agree_w"] >= delta else ch["err"]
            best_w = max(b["agree_w"], ch["agree_w"])
            return r["unet"] if best_w < tau else pick
        return f

    def best_cand(r):
        return min((cd["err"] for cd in r["cands"]), key=lambda e: (e["blob"], e["px"]))

    def oracle_all(r):
        return min([cd["err"] for cd in r["cands"]] + [r["unet"]], key=lambda e: (e["blob"], e["px"]))

    methods = {"chosen": chosen, "unet": lambda r: r["unet"], "S1 agree_w最高": S1}
    for tau in (0.90, 0.93, 0.95, 0.97):
        methods[f"S2 τ={tau}"] = S2(tau)
    for d in (0.01, 0.02, 0.05):
        methods[f"S3 δ={d}"] = S3(d)
    for tau in (0.93, 0.95):
        for d in (0.01, 0.02):
            methods[f"S2+S3 τ={tau} δ={d}"] = S23(tau, d)
    methods["候选池上限"] = best_cand
    methods["全池上限(+unet)"] = oracle_all
    rows = [r for r in per if r["label_ok"]]
    summary = {"n_frame_ok": len(per), "n_label_ok": len(rows),
               "n_cand_hist": {str(k): sum(1 for r in rows if r["n_cand"] == k) for k in sorted({r["n_cand"] for r in rows})},
               "label_ok": {m: agg(rows, f) for m, f in methods.items()}}
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        summary[f"label_ok/{v}"] = {m: agg(rr, f) for m, f in methods.items()}
    summary["frame_ok_all"] = {m: agg(per, f) for m, f in methods.items()}
    jdump(summary, out / "summary.json")
    print(f"frame_ok {len(per)}  label_ok {len(rows)}  候选数分布 {summary['n_cand_hist']}")
    print(f"{'method':26s} px_mean median  le20px  blob>=60 blob>=150")
    for m, x in summary["label_ok"].items():
        print(f"{m:26s} {x['px_mean']:7.1f} {x['px_median']:6.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}")
    for v in ("seam_ok", "ok", "moved", "overlap"):
        s = summary[f"label_ok/{v}"]
        print(f"-- {v} n={s['chosen']['n']} blob>=150: " + "  ".join(f"{m}={s[m]['blob_ge150']:.1%}" for m in ("chosen", "unet", "S1 agree_w最高", "S2 τ=0.95", "S2+S3 τ=0.95 δ=0.01", "候选池上限")))
    print(f"→ {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
