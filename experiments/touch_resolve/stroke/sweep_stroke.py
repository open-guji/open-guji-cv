# -*- coding: utf-8 -*-
"""参数扫描：U-Net 预测缓存到 out/stroke_eval/pred_cache.npz，只在主评测子集（frame_ok ∩ label_ok ∩ poly）上比各参数组合。

    .venv/Scripts/python experiments/touch_resolve/stroke/sweep_stroke.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_stroke import STROKE_OUT, UNetV2, cc_vote, err_stats, owner_from_seam, raw_owner_from_pred  # noqa: E402
from stroke_partition import stroke_partition  # noqa: E402
from common import INK_TH, OUT_ROOT, Loader, seam_chosen, seam_gold, window  # noqa: E402

GRID = {
    "default": {},
    "ang25": {"ang_max": 25.0},
    "ang40": {"ang_max": 40.0},
    "wr0.4": {"wr_min": 0.4},
    "wr0.65": {"wr_min": 0.65},
    "zone2": {"zone_r": 2, "bridge_len": 6},
    "ext0": {"ext_len": 0},
    "ext6": {"ext_len": 6},
    "neck0.7": {"neck_ratio": 0.7},
    "neck0.9": {"neck_ratio": 0.9},
    "gain8": {"split_min_gain": 8},
    "gain30": {"split_min_gain": 30},
    "nointerior": {"interior_split": False},
    "interior20": {"interior_gain": 20, "interior_frac": 0.5},
    "seg_only": {"chain": False},
    "nosplit": {"split_min_gain": 10 ** 9},
    "spur0": {"spur_len": 0},
    "spur7": {"spur_len": 7},
    "vote_core": {"core_rule": "vote"},
}


def main() -> int:
    L = Loader()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    cache_p = STROKE_OUT / "pred_cache.npz"
    cache = dict(np.load(cache_p)) if cache_p.exists() else {}
    net = None
    items = []
    for it in L.gold_items():
        if it.id not in frame_ok:
            continue
        e1 = exp1.get(it.id)
        if not e1:
            continue
        rk = e1["rank"]["gold"]
        if not (rk["fused_above"] and rk["fused_above"] <= 5 and rk["fused_below"] and rk["fused_below"] <= 5):
            continue
        if not (it.expected.get("polyline") and len(it.expected["polyline"]) >= 2):
            continue
        c, _ = L.resolve(it)
        if c is None or L.image_of(c) is None:
            continue
        img = L.image_of(c); win, y0, _ = window(c, img)
        key = c.id
        if key not in cache:
            if net is None:
                net = UNetV2()
            cache[key] = net.predict(win)
        items.append((c, win, y0, cache[key]))
    np.savez_compressed(cache_p, **cache)
    print(f"主子集 {len(items)} 条", flush=True)

    base = {}
    for c, win, y0, pred in items:
        W = (win < INK_TH).astype(np.uint8)
        og = owner_from_seam(W, seam_gold(c) - y0)
        raw = raw_owner_from_pred(pred, W)
        base[c.id] = {"unet_raw": err_stats(raw, og), "unet": err_stats(cc_vote(raw, W), og),
                      "chosen": err_stats(owner_from_seam(W, seam_chosen(c) - y0), og)}

    def row(name, errs):
        px = np.array([e[0] for e in errs]); bl = np.array([e[1] for e in errs])
        return f"{name:12s} mean {px.mean():6.1f} med {np.median(px):4.0f} p90 {np.percentile(px, 90):5.0f} | ≤20 {(px <= 20).mean():5.1%} | b≥60 {(bl >= 60).sum():3d} ({(bl >= 60).mean():5.1%}) | b≥150 {(bl >= 150).sum():3d} ({(bl >= 150).mean():5.1%})"

    ids = [c.id for c, *_ in items]
    for k in ("unet_raw", "unet", "chosen"):
        print(row(k, [base[i][k] for i in ids]))
    for name, prm in GRID.items():
        t0 = time.time(); errs = []
        wl = [0, 0, 0]
        for c, win, y0, pred in items:
            W = (win < INK_TH).astype(np.uint8)
            og = owner_from_seam(W, seam_gold(c) - y0)
            votes = (pred * W).astype(np.uint8)
            e = err_stats(stroke_partition(win, votes, prm).owner, og)
            errs.append(e)
            d = base[c.id]["unet"][0] - e[0]
            wl[0 if d > 10 else (2 if d < -10 else 1)] += 1
        print(row(name, errs) + f" | vs unet W/T/L {wl[0]}/{wl[1]}/{wl[2]}  {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
