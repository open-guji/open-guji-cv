# -*- coding: utf-8 -*-
"""实验六：现役缝 × U-Net 归属的「选择器」上限与简单规则。

    python experiments/touch_resolve/exp6_selector.py [--cc-max 400] [--books vol01,vol02,vol03]

背景（2026-09-14，frame_ok+label_ok n=673）：现役缝大块错(≥150px) 5.2%、U-Net 1.3%，而两者**同时**大块错只有 1 条
——逐条二选一的上限（oracle）大块错 0.1%、px 均值 9.7。问题变成：没有金标时，靠什么挑？
本实验对每条金标算：
  - 两法归属的**分歧区** D（墨像素里 unet != chosen）：dis_px、dis_blob（最大连通块）；
  - 每个分歧连通块上 U-Net 的平均置信度（softmax 两类之差）、面积；
  - 规则：R_chosen / R_unet / R_dis(T)=「分歧最大块 ≥ T 才用 unet，否则 chosen」/
          R_cc(p)=「逐个分歧块：unet 置信 ≥ p 用 unet，否则 chosen」/ oracle。
尺子沿用实验三：err_px、err_blob（≥60 一笔划错边，≥150 大块）。
产出 out/exp6/per_case.json、summary.json、viz/（分歧最大的 24 条：左原图，中 chosen，右 unet，红=归上 蓝=归下）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, Loader, OUT_ROOT, jdump, seam_chosen, seam_gold, window  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from templates import owner_from_seam  # noqa: E402
from train_partition_unet_v2 import MODEL_DIR, build_model, make_input, to_canvas  # noqa: E402


def unet_owner(net, dev, win: np.ndarray, cc_max: int | None):
    import torch
    W = (win < INK_TH).astype(np.uint8)
    cimg, _, s = to_canvas(win, top=8)
    x = make_input(cimg)[None].to(dev)
    with torch.no_grad():
        logits = net(x)[0]
        prob = torch.softmax(logits, 0).cpu().numpy()
    prob = prob[:, 8:]
    h, w = win.shape
    if s < 1.0:
        ph, pw = int(h * s), int(w * s)
        prob = np.stack([cv2.resize(prob[k][:ph, :pw], (w, h), interpolation=cv2.INTER_LINEAR) for k in range(prob.shape[0])])
    else:
        prob = prob[:, :h, :w]
    pA = prob[1]
    pB = prob[2] if prob.shape[0] > 2 else 1 - prob[1]
    raw = np.where(W > 0, np.where(pA >= pB, 1, 2), 0).astype(np.uint8)
    conf = np.abs(pA - pB)                      # 两类置信差
    owner = raw.copy()
    n_cc, lab, st, _ = cv2.connectedComponentsWithStats(W, connectivity=8)
    for i in range(1, n_cc):
        if cc_max is not None and st[i, cv2.CC_STAT_AREA] > cc_max:
            continue
        m = lab == i
        v = raw[m]
        nA, nB = int((v == 1).sum()), int((v == 2).sum())
        if nA >= 0.85 * (nA + nB):
            owner[m] = 1
        elif nB >= 0.85 * (nA + nB):
            owner[m] = 2
    return W, owner, conf


def main() -> int:
    import torch
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc-max", type=int, default=400)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--ckpt", default=None)
    a = ap.parse_args()
    ck = Path(a.ckpt) if a.ckpt else MODEL_DIR / "partition_unet_v2.pt"
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = build_model().to(dev)
    net.load_state_dict(torch.load(ck, map_location=dev)["state"])
    net.eval()
    L = Loader()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    out = OUT_ROOT / "exp6"
    (out / "viz").mkdir(parents=True, exist_ok=True)
    per = []
    keep = []
    for it in L.gold_items(books=a.books.split(",")):
        if it.id not in frame_ok:
            continue
        c, _ = L.resolve(it)
        if c is None or L.image_of(c) is None:
            continue
        e1 = exp1.get(c.id)
        rk = (e1 or {}).get("rank", {}).get("gold", {})
        label_ok = bool(rk.get("fused_above") and rk["fused_above"] <= 5 and rk.get("fused_below") and rk["fused_below"] <= 5)
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        W, ou, conf = unet_owner(net, dev, win, a.cc_max)
        og = owner_from_seam(W, seam_gold(c) - y0)
        oc = owner_from_seam(W, seam_chosen(c) - y0)
        D = (W > 0) & (ou != oc)
        rec = {"id": c.id, "verdict": c.verdict, "book": c.book, "poly": bool(c.gold_poly),
               "label_ok": label_ok, "err": {}, "dis": {}}
        for k, o in (("chosen", oc), ("unet", ou)):
            n, blob = err_stats(o, og)
            rec["err"][k] = {"px": n, "blob": blob}
        n_d = int(D.sum())
        blobs = []
        k = 0
        lab = None
        if n_d:
            k, lab, st, _ = cv2.connectedComponentsWithStats(D.astype(np.uint8), connectivity=8)
            for i in range(1, k):
                m = lab == i
                u_ok = float((ou[m] == og[m]).mean())
                c_ok = float((oc[m] == og[m]).mean())
                blobs.append({"area": int(st[i, cv2.CC_STAT_AREA]), "conf": round(float(conf[m].mean()), 4),
                              "unet_right": round(u_ok, 3), "chosen_right": round(c_ok, 3)})
        rec["dis"] = {"px": n_d, "blob": max((b["area"] for b in blobs), default=0), "blobs": blobs}
        rec["rule"] = {}
        for p in (0.0, 0.3, 0.5, 0.7, 0.9):
            o = oc.copy()
            if n_d:
                for i in range(1, k):
                    m = lab == i
                    if float(conf[m].mean()) >= p:
                        o[m] = ou[m]
            n, blob = err_stats(o, og)
            rec["rule"][f"cc_p{p}"] = {"px": n, "blob": blob}
        for T in (60, 100, 150, 200):
            o = ou if rec["dis"]["blob"] >= T else oc
            n, blob = err_stats(o, og)
            rec["rule"][f"dis_T{T}"] = {"px": n, "blob": blob}
        per.append(rec)
        keep.append((rec, win, oc, ou))
    jdump(per, out / "per_case.json")

    def agg(rs, get):
        px = np.array([get(r)["px"] for r in rs])
        bl = np.array([get(r)["blob"] for r in rs])
        if not px.size:
            return None
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
                "blob_ge150": round(float((bl >= 150).mean()), 4)}

    rows = [r for r in per if r["label_ok"]]
    methods = {"chosen": lambda r: r["err"]["chosen"], "unet": lambda r: r["err"]["unet"],
               "oracle": lambda r: min((r["err"]["chosen"], r["err"]["unet"]), key=lambda e: (e["blob"], e["px"]))}
    for name in per[0]["rule"]:
        methods[name] = (lambda nm: (lambda r: r["rule"][nm]))(name)
    summary = {"n_frame_ok": len(per), "n_label_ok": len(rows), "cc_max": a.cc_max,
               "label_ok": {m: agg(rows, f) for m, f in methods.items()}}
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        summary[f"label_ok/{v}"] = {m: agg(rr, f) for m, f in methods.items()}
    bl = [b for r in rows for b in r["dis"]["blobs"] if b["area"] >= 60]
    u = np.array([b["conf"] for b in bl if b["unet_right"] >= 0.8 and b["chosen_right"] < 0.2])
    cch = np.array([b["conf"] for b in bl if b["chosen_right"] >= 0.8 and b["unet_right"] < 0.2])
    summary["dis_blobs_ge60"] = {
        "n": len(bl), "unet_right": int(u.size), "chosen_right": int(cch.size),
        "conf_when_unet_right": {"mean": round(float(u.mean()), 3) if u.size else None,
                                 "p25": round(float(np.percentile(u, 25)), 3) if u.size else None},
        "conf_when_chosen_right": {"mean": round(float(cch.mean()), 3) if cch.size else None,
                                   "p75": round(float(np.percentile(cch, 75)), 3) if cch.size else None}}
    jdump(summary, out / "summary.json")
    print(f"frame_ok {len(per)}  label_ok {len(rows)}")
    print(f"{'method':10s} px_mean  median  le20px   blob>=60  blob>=150")
    for m, x in summary["label_ok"].items():
        print(f"{m:10s} {x['px_mean']:7.1f} {x['px_median']:7.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}")
    print("分歧块(>=60px):", json.dumps(summary["dis_blobs_ge60"], ensure_ascii=False))
    worst = sorted(keep, key=lambda p: -p[0]["dis"]["blob"])[:24]
    for rec, win, oc, ou in worst:
        vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
        panels = [vis]
        for o in (oc, ou):
            ov = vis.copy()
            ov[o == 1] = (0, 0, 220)
            ov[o == 2] = (220, 90, 0)
            panels.append(cv2.addWeighted(vis, 0.35, ov, 0.65, 0))
        sheet = np.concatenate(panels, axis=1)
        cv2.imwrite(str(out / "viz" / (rec["id"].replace(":", "_") + ".png")),
                    cv2.resize(sheet, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    print(f"→ {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
