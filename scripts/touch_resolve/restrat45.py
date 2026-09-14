# -*- coding: utf-8 -*-
"""实验四（字形库纯度 out/exp4）与实验五（身份敏感度 out/exp5）按 frame_ok 重分层。

    python scripts/touch_resolve/restrat45.py
"""
from __future__ import annotations

import json

import numpy as np

from common import OUT_ROOT, jdump

frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
print(f"frame_ok {len(frame_ok)}")

# ── 实验五 ──
p5 = OUT_ROOT / "exp5" / "per_case.json"
if p5.exists():
    per = json.loads(p5.read_text(encoding="utf-8"))
    rows = [r for r in per if r["id"] in frame_ok]
    print(f"\n== exp5 身份敏感度（frame_ok + 标签可信 + 带折线）n={len(rows)} / 原 {len(per)}")

    def agg(rs, k):
        px = np.array([r["err"][k]["px"] for r in rs if k in r["err"]]); bl = np.array([r["err"][k]["blob"] for r in rs if k in r["err"]])
        return None if px.size == 0 else dict(n=int(px.size), px_mean=round(float(px.mean()), 1), px_median=float(np.median(px)),
                                              px_p90=float(np.percentile(px, 90)), le20px=round(float((px <= 20).mean()), 4),
                                              blob_ge60=round(float((bl >= 60).mean()), 4))
    out = {}
    for sname, rs in (("all", rows), ("top1_correct", [r for r in rows if r["top1_correct"]]),
                      ("top1_wrong", [r for r in rows if not r["top1_correct"]]),
                      ("moved", [r for r in rows if r["verdict"] == "moved"])):
        out[sname] = {k: agg(rs, k) for k in ("gold", "top1", "rank2", "swap_worse", "chosen")}
        print(f"  -- {sname} n={len(rs)}   mean / median / p90 | ≤20px | blob≥60")
        for k in ("gold", "top1", "rank2", "swap_worse", "chosen"):
            x = out[sname][k]
            if x:
                print(f"     {k:10s} {x['px_mean']:6.1f} / {x['px_median']:4.0f} / {x['px_p90']:5.0f} | {x['le20px']:6.1%} | {x['blob_ge60']:6.1%}")
    # 逐条：rank2 与 gold 的差
    d = np.array([r["err"]["rank2"]["px"] - r["err"]["gold"]["px"] for r in rows if "rank2" in r["err"] and "gold" in r["err"]])
    if d.size:
        print(f"  rank2 − gold 逐条差：|差|≤10px 的占 {np.mean(np.abs(d) <= 10):.1%}，rank2 更差 >30px 的占 {np.mean(d > 30):.1%}，更好 >30px 的占 {np.mean(d < -30):.1%}")
    jdump(out, OUT_ROOT / "exp5" / "summary_frame_ok.json")

# ── 实验四 ──
p4 = OUT_ROOT / "exp4" / "per_case.json"
if p4.exists():
    per = json.loads(p4.read_text(encoding="utf-8"))
    rows = [r for r in per if r["id"] in frame_ok]
    print(f"\n== exp4 字形库纯度（frame_ok + 标签可信）n={len(rows)} / 原 {len(per)}")
    out = {}
    for sname, rs in (("all", rows), ("poly", [r for r in rows if r["poly"]]), ("moved", [r for r in rows if r["verdict"] == "moved"])):
        out[sname] = {}
        print(f"  -- {sname} n={len(rs)}   半字块 vs 库中同字刻例 cov  mean / median / p10")
        for k in ("gold", "chosen", "straight", "partition", "unet"):
            v = np.array([r["cov"][f"{k}_{s}"] for r in rs for s in ("above", "below") if f"{k}_{s}" in r["cov"]])
            if v.size:
                out[sname][k] = dict(n=int(v.size), mean=round(float(v.mean()), 4), median=round(float(np.median(v)), 4), p10=round(float(np.percentile(v, 10)), 4))
                print(f"     {k:10s} {v.mean():.4f} / {np.median(v):.4f} / {np.percentile(v, 10):.4f}  (n={v.size})")
        for k in ("partition", "unet"):
            w = l = t = 0
            for r in rs:
                for s in ("above", "below"):
                    a1, b1 = r["cov"].get(f"{k}_{s}"), r["cov"].get(f"chosen_{s}")
                    if a1 is None or b1 is None:
                        continue
                    dd = a1 - b1; w += dd > 0.005; l += dd < -0.005; t += abs(dd) <= 0.005
            out[sname][f"{k}_vs_chosen"] = dict(win=int(w), tie=int(t), loss=int(l))
            print(f"     {k} vs chosen（容差 0.005）: win {w} tie {t} loss {l}")
    jdump(out, OUT_ROOT / "exp4" / "summary_frame_ok.json")
