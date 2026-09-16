# -*- coding: utf-8 -*-
"""实验四：归属好坏的下游价值尺子——切出来的字块与字形库同字刻例的弹性贴合度（入库纯度）。

    python experiments/touch_resolve/exp4_glyph_purity.py [--unet CKPT] [--limit N]

识别对切法不敏感（实验一 / 三），但字形库要的是干净字块：邻字残笔混进来会拉低与同字刻例的 cov、
甚至被 never-match 护栏挡掉。对每条标签可信的金标，四种归属各切出上下两半，归一化到 64² 后与
本书字形库里同字的刻例（排除待测格自身）逐对跑 `verify_pair_elastic`，取最高 cov：
  chosen（现役缝）/ straight / gold（人工金标缝，上界参考）/ partition（模板归属 v2）/ unet（类别无关网络）
报各归属的 cov 均值、过 same 闸（≥0.996）的比例、与 gold 切法的差距。
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from common import (INK_TH, GlyphIndex, Loader, OUT_ROOT, half_patch, jdump, normalize, seam_chosen, seam_gold,
                    seam_straight, side_masks, window)
from exp2_verify_partition import column_char_height
from templates import Registrar, TemplateBank, owner_from_seam


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unet", default="D:/data/touch_synth/models/partition_unet_v2.pt")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--n-exemplars", type=int, default=4)
    a = ap.parse_args()
    out = OUT_ROOT / "exp4"; out.mkdir(parents=True, exist_ok=True)
    from open_guji_cv.clustering.verify import verify_pair_elastic, ELASTIC_COV_HIGH

    L = Loader(); gi = GlyphIndex(); bank = TemplateBank(glyphs=gi, n_exemplars=2)
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    net = None
    if a.unet and Path(a.unet).exists():
        import torch
        from train_partition_unet_v2 import build_model, make_input, to_canvas
        net = build_model(); net.load_state_dict(torch.load(a.unet, map_location="cpu")["state"]); net.eval()

    def unet_owner(win, W):
        import torch
        cimg, _, s = to_canvas(win, top=8)
        with torch.no_grad():
            pred = net(make_input(cimg)[None]).argmax(1)[0].numpy().astype(np.uint8)
        pred = pred[8:]
        h, w = win.shape
        if s < 1.0:
            pred = cv2.resize(pred[: int(h * s), : int(w * s)], (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            pred = pred[:h, :w]
        raw = np.where(W > 0, np.where(pred == 0, 2, pred), 0).astype(np.uint8); owner = raw.copy()
        n, lab = cv2.connectedComponents(W, connectivity=8)
        for i in range(1, n):
            m = lab == i; v = raw[m]; nA, nB = int((v == 1).sum()), int((v == 2).sum())
            if nA >= 0.85 * (nA + nB):
                owner[m] = 1
            elif nB >= 0.85 * (nA + nB):
                owner[m] = 2
        return owner

    cases = []
    for it in L.gold_items(need_chars=True):
        c, _ = L.resolve(it)
        if c is None or not c.has_chars() or L.image_of(c) is None or c.id not in exp1:
            continue
        rk = exp1[c.id]["rank"]["gold"]
        if not (rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5):
            continue
        cases.append(c)
    if a.limit:
        cases = cases[: a.limit]
    print(f"标签可信用例 {len(cases)}")

    per = []; t0 = time.time()
    agg = defaultdict(list)
    for ci, case in enumerate(cases):
        img = L.image_of(case); win, y0, _ = window(case, img); W = (win < INK_TH).astype(np.uint8)
        exclude = (case.page, case.col, {case.up.pos - 1, case.up.pos, case.dn.pos - 1, case.dn.pos})
        owners = {"chosen": owner_from_seam(W, seam_chosen(case) - y0),
                  "straight": owner_from_seam(W, seam_straight(case) - y0),
                  "gold": owner_from_seam(W, seam_gold(case) - y0)}
        ch_h, _ = column_char_height(L, case)
        TA = bank.get(case.char_above, ch_h, exclude=exclude); TB = bank.get(case.char_below, ch_h, exclude=exclude)
        if TA and TB:
            reg = Registrar(W); best = None
            for A in TA:
                for B in TB:
                    pa, pb, sc = reg.register(A, B)
                    if best is None or sc > best[0]:
                        best = (sc, A, pa, B, pb)
            owners["partition"] = reg.partition(best[1], best[2], best[3], best[4])[0]
        if net is not None:
            owners["unet"] = unet_owner(win, W)
        rec = {"id": case.id, "verdict": case.verdict, "poly": bool(case.gold_poly), "pair": case.char_above + case.char_below, "cov": {}}
        for side, val, ch in (("above", 1, case.char_above), ("below", 2, case.char_below)):
            exs = gi.exemplars(ch, exclude=exclude, n=a.n_exemplars)
            if not exs:
                continue
            ex_norm = [normalize((255 - e * 255).astype(np.uint8)) for e in exs]
            for k, o in owners.items():
                hp = half_patch(win, o == val)
                if hp is None:
                    continue
                q = normalize(hp)
                cov = max(verify_pair_elastic(q, e).f1 for e in ex_norm)
                rec["cov"][f"{k}_{side}"] = round(float(cov), 4)
                agg[k].append(float(cov))
                agg[f"{k}_same"].append(float(cov >= ELASTIC_COV_HIGH))
        per.append(rec)
        if (ci + 1) % 50 == 0:
            print(f"  {ci + 1}/{len(cases)} {time.time() - t0:.0f}s", flush=True)

    summary = {"n": len(per)}
    print("\n== 半字块 vs 库中同字刻例 弹性 cov（越高越干净）  mean / median / p10 | 过 same 闸(≥0.996)")
    for k in ("gold", "chosen", "straight", "partition", "unet"):
        if agg.get(k):
            v = np.array(agg[k]); s = np.mean(agg[f"{k}_same"])
            summary[k] = {"n": int(v.size), "mean": round(float(v.mean()), 4), "median": round(float(np.median(v)), 4),
                          "p10": round(float(np.percentile(v, 10)), 4), "same_rate": round(float(s), 4)}
            print(f"  {k:10s} {v.mean():.4f} / {np.median(v):.4f} / {np.percentile(v, 10):.4f} | {s:.1%}  (n={v.size})")
    # 逐条：partition / unet 比 chosen 高的比例（同侧比）
    for k in ("partition", "unet"):
        w = l = t = 0
        for r in per:
            for side in ("above", "below"):
                a1, b1 = r["cov"].get(f"{k}_{side}"), r["cov"].get(f"chosen_{side}")
                if a1 is None or b1 is None:
                    continue
                d = a1 - b1
                w += d > 0.005; l += d < -0.005; t += abs(d) <= 0.005
        summary[f"{k}_vs_chosen"] = {"win": w, "tie": t, "loss": l}
        print(f"  {k} vs chosen（容差 0.005）: win {w} tie {t} loss {l}")
    jdump(per, out / "per_case.json"); jdump(summary, out / "summary.json")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
