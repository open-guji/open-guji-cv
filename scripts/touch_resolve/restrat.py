# -*- coding: utf-8 -*-
"""按「金标坐标系与当下列图一致」(frame_ok: |col_h_gold − img_h| ≤ 2) 重新分层统计 exp3 / unet 的 per_case。

    python scripts/touch_resolve/restrat.py out/exp3_glyph out/exp3_glyph_v2 out/unet_partition_unet_vol01
"""
from __future__ import annotations
import json, sys
import numpy as np
from common import Loader, OUT_ROOT, jdump

fo_path = OUT_ROOT / "frame_ok.json"
if fo_path.exists():
    frame_ok = set(json.loads(fo_path.read_text(encoding="utf-8")))
else:
    L = Loader(); frame_ok = set()
    for it in L.gold_items():
        c, _ = L.resolve(it)
        if c is None: continue
        img = L.image_of(c); ch = it.expected.get("col_h")
        if ch and abs(int(ch) - img.shape[0]) <= 2:
            frame_ok.add(it.id)
    jdump(sorted(frame_ok), fo_path)
print(f"frame_ok 金标 {len(frame_ok)} 条")

def agg(rows, key):
    px = np.array([r["err"][key]["px"] for r in rows if key in r["err"]]); bl = np.array([r["err"][key]["blob"] for r in rows if key in r["err"]])
    return None if px.size == 0 else dict(n=int(px.size), px_mean=round(float(px.mean()), 1), px_median=float(np.median(px)),
                                          px_p90=float(np.percentile(px, 90)), le20px=round(float((px <= 20).mean()), 4),
                                          blob_ge60=round(float((bl >= 60).mean()), 4), blob_ge150=round(float((bl >= 150).mean()), 4))

for d in sys.argv[1:]:
    p = OUT_ROOT / d.replace("out/", "") / "per_case.json"
    per = json.loads(p.read_text(encoding="utf-8"))
    keys = [k for k in ("partition", "unet", "derived_seam", "chosen", "straight", "best_cand") if any(k in r["err"] for r in per)]
    print(f"\n== {d}  (n={len(per)})")
    strata = {
        "frame_ok": [r for r in per if r["id"] in frame_ok],
        "frame_ok+label_ok": [r for r in per if r["id"] in frame_ok and r.get("label_ok")],
        "frame_ok+label_ok+poly": [r for r in per if r["id"] in frame_ok and r.get("label_ok") and r.get("poly")],
    }
    for v in ("seam_ok", "moved", "ok", "overlap"):
        strata[f"frame_ok+label_ok/{v}"] = [r for r in per if r["id"] in frame_ok and r.get("label_ok") and r["verdict"] == v]
    out = {}
    for sname, rows in strata.items():
        out[sname] = {k: agg(rows, k) for k in keys}
        print(f"  -- {sname} n={len(rows)}   mean / median / p90 | ≤20px | blob≥60 | blob≥150")
        for k in keys:
            x = out[sname][k]
            if x: print(f"     {k:13s} {x['px_mean']:6.1f} / {x['px_median']:4.0f} / {x['px_p90']:5.0f} | {x['le20px']:6.1%} | {x['blob_ge60']:6.1%} | {x['blob_ge150']:6.1%}")
        # 归属后识别
        for rk in ("recog_partition", "recog_unet", "recog_chosen", "recog_gold"):
            v = [int(r[rk]["above"] == 1 and r[rk]["below"] == 1) for r in rows if r.get(rk) and "above" in r[rk] and "below" in r[rk]]
            if v: print(f"     {rk:16s} both@1 {np.mean(v):.1%} (n={len(v)})")
    jdump(out, OUT_ROOT / d.replace("out/", "") / "summary_frame_ok.json")
