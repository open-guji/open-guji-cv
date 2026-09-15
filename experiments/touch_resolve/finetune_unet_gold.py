# -*- coding: utf-8 -*-
"""U-Net v2 在**真金标**上按页五折微调（折外评测），看归属网络本身还能好多少。

    python experiments/touch_resolve/finetune_unet_gold.py [--epochs 15] [--lr 2e-4] [--synth 4000] [--cc-max 400]

动机（2026-09-14 实验七～九）：候选池 + 各种裁判都停在大块错 ~1.5%；残余 10 条里 5 条是 U-Net 自己把游离部件翻了边
（書的底日、陽的阝……），另 5 条是几何候选全错、只有 U-Net 对但裁判不敢信它。两边的瓶颈都是 U-Net 在真数据上的准头，
而它至今只见过合成对（零人工标注）。现在 frame_ok 金标有 906 条，够做一次五折微调看上限。
做法：
  - 样本 = 双格窗口灰度 + 金标缝导出的逐像素归属（0 背景 / 1 上 / 2 下），verdict=overlap 的不进训练（折中线不是像素真值），但参与评测；
  - 按页分 5 折；每折从 partition_unet_v2.pt 起微调，AdamW + 余弦，增广同 v2（纵横缩放、左侧平移、顶部偏移）；
    每个 epoch 混入等量随机合成对，防止忘掉合成分布；
  - 折外：U-Net 归属（pA vs pB + 连通体多数票 cc≤400）、以它当裁判的 S1、S1+U(T=150)，与基线（原 U-Net、现役缝、候选池上限）同表。
产出 out/unet_ft/per_case.json、summary.json，折模型 D:/data/touch_synth/models/ft/fold{k}.pt。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, Loader, OUT_ROOT, jdump, seam_chosen, seam_gold, seams_candidates, window  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from exp6_selector import unet_owner  # noqa: E402
from exp7_select_pool import dis_blob  # noqa: E402
from templates import owner_from_seam  # noqa: E402
from train_partition_unet_v2 import MODEL_DIR, build_model, make_input, to_canvas  # noqa: E402


def augment(g: np.ndarray, o: np.ndarray):
    sy = random.uniform(0.85, 1.05)
    sx = random.uniform(0.95, 1.03)
    if abs(sy - 1) > 0.01 or abs(sx - 1) > 0.01:
        g = cv2.resize(g, (max(8, int(g.shape[1] * sx)), max(8, int(g.shape[0] * sy))), interpolation=cv2.INTER_AREA)
        o = cv2.resize(o, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
    dx = random.randint(0, 8)
    g = np.pad(g, ((0, 0), (dx, 0)), constant_values=255)
    o = np.pad(o, ((0, 0), (dx, 0)), constant_values=0)
    top = random.randint(0, 40)
    img, own, _ = to_canvas(g, o, top=top)
    return img, own


def to_xy(img, own):
    import torch
    y = torch.from_numpy(own.astype(np.int64))
    y[y == 3] = -1
    return make_input(img), y


def load_synth(n: int, roots=("D:/data/touch_synth/vol01", "D:/data/touch_synth/vol02")):
    items = []
    metas = []
    for r in roots:
        root = Path(r)
        for l in (root / "meta.jsonl").read_text(encoding="utf-8").splitlines():
            metas.append((root, json.loads(l)))
    random.Random(1).shuffle(metas)
    for root, m in metas[:n]:
        g = cv2.imread(str(root / "pairs" / f"{m['i']:06d}.png"), 0)
        o = cv2.imread(str(root / "pairs" / f"{m['i']:06d}_own.png"), 0)
        if g is not None and o is not None:
            items.append((g, o))
    return items


def main() -> int:
    import torch
    import torch.nn.functional as F
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--synth", type=int, default=4000)
    ap.add_argument("--cc-max", type=int, default=400)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--books", default="vol01,vol02,vol03")
    a = ap.parse_args()
    t0 = time.time()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    L = Loader()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    base7 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp7" / "per_case.json").read_text(encoding="utf-8"))}
    cases = []
    for it in L.gold_items(books=a.books.split(",")):
        if it.id not in frame_ok:
            continue
        c, _ = L.resolve(it)
        if c is None or L.image_of(c) is None:
            continue
        img = L.image_of(c)
        win, y0, _ = window(c, img)
        W = (win < INK_TH).astype(np.uint8)
        og = owner_from_seam(W, seam_gold(c) - y0).astype(np.uint8)
        rk = (exp1.get(c.id) or {}).get("rank", {}).get("gold", {})
        label_ok = bool(rk.get("fused_above") and rk["fused_above"] <= 5 and rk.get("fused_below") and rk["fused_below"] <= 5)
        cases.append({"case": c, "win": win, "y0": y0, "W": W, "og": og, "label_ok": label_ok,
                      "page": f"{c.book}:{c.page}", "verdict": c.verdict})
    print(f"金标窗口 {len(cases)}（frame_ok），{time.time() - t0:.0f}s", flush=True)
    synth = load_synth(a.synth)
    print(f"合成对 {len(synth)}，{time.time() - t0:.0f}s", flush=True)
    pages = sorted({x["page"] for x in cases})
    random.Random(0).shuffle(pages)
    folds = [set(pages[i::a.folds]) for i in range(a.folds)]
    base_sd = torch.load(MODEL_DIR / "partition_unet_v2.pt", map_location=dev)["state"]
    cw = torch.tensor([0.2, 1.0, 1.0], device=dev)
    (MODEL_DIR / "ft").mkdir(parents=True, exist_ok=True)
    out = OUT_ROOT / "unet_ft"
    out.mkdir(parents=True, exist_ok=True)
    per = []
    for k in range(a.folds):
        tr = [x for x in cases if x["page"] not in folds[k] and x["verdict"] != "overlap"]
        te = [x for x in cases if x["page"] in folds[k]]
        net = build_model().to(dev)
        net.load_state_dict(base_sd)
        opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
        steps_per_ep = (2 * len(tr)) // a.bs
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * steps_per_ep, pct_start=0.15)
        for ep in range(a.epochs):
            net.train()
            pool = [(x["win"], x["og"]) for x in tr] + random.sample(synth, min(len(synth), len(tr)))
            random.shuffle(pool)
            tot = 0.0
            n = 0
            for i in range(0, len(pool) - a.bs + 1, a.bs):
                xs, ys = [], []
                for g, o in pool[i:i + a.bs]:
                    img, own = augment(g, o)
                    xx, yy = to_xy(img, own)
                    xs.append(xx)
                    ys.append(yy)
                x = torch.stack(xs).to(dev)
                y = torch.stack(ys).to(dev)
                loss = F.cross_entropy(net(x), y, weight=cw, ignore_index=-1)
                opt.zero_grad()
                loss.backward()
                opt.step()
                sched.step()
                tot += float(loss) * x.size(0)
                n += x.size(0)
            print(f"fold {k} ep {ep + 1}/{a.epochs} loss {tot / max(n, 1):.4f}  {time.time() - t0:.0f}s", flush=True)
        torch.save({"state": net.state_dict(), "fold": k, "v": "ft"}, MODEL_DIR / "ft" / f"fold{k}.pt")
        net.eval()
        for x in te:
            c = x["case"]
            win, y0, W, og = x["win"], x["y0"], x["W"], x["og"]
            _, ou, conf = unet_owner(net, dev, win, a.cc_max)
            ink = W > 0
            cwv = conf[ink]
            sc = seam_chosen(c)
            members = []
            seen = []
            for kind, seam in seams_candidates(c):
                key = tuple(int(v) for v in seam)
                if key in seen:
                    continue
                seen.append(key)
                o = owner_from_seam(W, seam - y0)
                nn_, blob = err_stats(o, og)
                eq = (o[ink] == ou[ink])
                members.append({"kind": kind, "is_chosen": bool(np.array_equal(seam, sc)), "err": {"px": nn_, "blob": blob},
                                "agree_w": float((cwv * eq).sum() / max(cwv.sum(), 1e-6)) if eq.size else 1.0,
                                "dis_unet": dis_blob(o, ou, W)})
            if not any(m["is_chosen"] for m in members):
                oc = owner_from_seam(W, sc - y0)
                nn_, blob = err_stats(oc, og)
                eq = (oc[ink] == ou[ink])
                members.append({"kind": "chosen", "is_chosen": True, "err": {"px": nn_, "blob": blob},
                                "agree_w": float((cwv * eq).sum() / max(cwv.sum(), 1e-6)), "dis_unet": dis_blob(oc, ou, W)})
            nu, bu = err_stats(ou, og)
            b7 = base7.get(c.id)
            per.append({"id": c.id, "fold": k, "verdict": c.verdict, "label_ok": x["label_ok"],
                        "unet_ft": {"px": nu, "blob": bu}, "unet_base": (b7 or {}).get("unet"),
                        "members": members})
        print(f"fold {k} 折外 {len(te)} 条评完  {time.time() - t0:.0f}s", flush=True)
    jdump(per, out / "per_case.json")

    def agg(errs):
        errs = [e for e in errs if e]
        px = np.array([e["px"] for e in errs]); bl = np.array([e["blob"] for e in errs])
        return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
                "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
                "blob_ge150": round(float((bl >= 150).mean()), 4)}

    def fmt(x):
        return f"{x['px_mean']:7.1f} {x['px_median']:6.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}"

    def chosen(r):
        return next(m for m in r["members"] if m["is_chosen"])["err"]

    def s1m(r):
        return max(r["members"], key=lambda m: (m["agree_w"], m["is_chosen"]))

    def S1(r):
        return s1m(r)["err"]

    def S1U(T):
        def f(r):
            b = s1m(r)
            return r["unet_ft"] if b["dis_unet"] >= T else b["err"]
        return f

    def best_cand(r):
        return min((m["err"] for m in r["members"]), key=lambda e: (e["blob"], e["px"]))

    def oracle(r):
        return min([m["err"] for m in r["members"]] + [r["unet_ft"]], key=lambda e: (e["blob"], e["px"]))

    methods = {"chosen": chosen, "unet_base": lambda r: r["unet_base"], "unet_ft(折外)": lambda r: r["unet_ft"],
               "S1 用ft当裁判": S1, "S1+U(150) ft": S1U(150), "S1+U(100) ft": S1U(100), "S1+U(60) ft": S1U(60),
               "候选池上限": best_cand, "全池上限(+ft)": oracle}
    rows = [r for r in per if r["label_ok"]]
    summary = {"n_frame_ok": len(per), "n_label_ok": len(rows), "epochs": a.epochs, "lr": a.lr, "synth": a.synth,
               "label_ok": {}, "frame_ok_all": {}, "by_verdict": {}}
    print(f"\n折外汇总 label_ok n={len(rows)}")
    print(f"{'method':20s} px_mean median  le20px  blob>=60 blob>=150")
    for name, f in methods.items():
        x = agg([f(r) for r in rows])
        summary["label_ok"][name] = x
        summary["frame_ok_all"][name] = agg([f(r) for r in per])
        print(f"{name:20s} {fmt(x)}")
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        summary["by_verdict"][v] = {name: agg([f(r) for r in rr]) for name, f in methods.items()}
        print(f"-- {v} n={len(rr)} blob>=150: " + "  ".join(f"{m}={summary['by_verdict'][v][m]['blob_ge150']:.1%}" for m in ("chosen", "unet_base", "unet_ft(折外)", "S1 用ft当裁判", "S1+U(150) ft", "全池上限(+ft)")))
    jdump(summary, out / "summary.json")
    print(f"→ {out}  {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
