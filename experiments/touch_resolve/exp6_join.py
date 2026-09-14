# -*- coding: utf-8 -*-
"""实验六·续：把实验三（模板归属 v3）的逐条结果并进来，看三法联合的上限与候选池上限。

    python experiments/touch_resolve/exp6_join.py [--exp3 out/exp3_glyph_v3]

按 id 对齐 out/exp6/per_case.json（chosen / unet / 规则）与 exp3 的 per_case.json（partition / straight / best_cand），
只算 frame_ok + 标签可信且两边都有的条目。输出：
  - 各单法与规则；
  - 候选池上限 best_cand（直线 / 窄走廊 / 宽走廊里离金标最近的那条）；
  - 二选一 {chosen, unet}、三选一 {chosen, unet, partition}、四选一 {+best_cand} 的上限。
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from common import OUT_ROOT, jdump


def agg(rows, get):
    px = np.array([get(r)["px"] for r in rows])
    bl = np.array([get(r)["blob"] for r in rows])
    if not px.size:
        return None
    return {"n": int(px.size), "px_mean": round(float(px.mean()), 1), "px_median": float(np.median(px)),
            "le20px": round(float((px <= 20).mean()), 4), "blob_ge60": round(float((bl >= 60).mean()), 4),
            "blob_ge150": round(float((bl >= 150).mean()), 4)}


def best(*errs):
    return min(errs, key=lambda e: (e["blob"], e["px"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp3", default="out/exp3_glyph_v3")
    a = ap.parse_args()
    e6 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp6" / "per_case.json").read_text(encoding="utf-8"))}
    e3 = {r["id"]: r for r in json.loads((OUT_ROOT / a.exp3.replace("out/", "") / "per_case.json").read_text(encoding="utf-8"))}
    ids = [i for i, r in e6.items() if r["label_ok"] and i in e3 and "partition" in e3[i]["err"]]
    rows = [{"id": i, "verdict": e6[i]["verdict"], "e6": e6[i], "e3": e3[i]} for i in ids]
    print(f"exp6 label_ok {sum(1 for r in e6.values() if r['label_ok'])}，与 {a.exp3} 对上 {len(rows)}")
    methods = {
        "chosen": lambda r: r["e6"]["err"]["chosen"],
        "straight": lambda r: r["e3"]["err"]["straight"],
        "unet": lambda r: r["e6"]["err"]["unet"],
        "partition(模板)": lambda r: r["e3"]["err"]["partition"],
        "rule_dis_T150": lambda r: r["e6"]["rule"]["dis_T150"],
        "rule_cc_p0.7": lambda r: r["e6"]["rule"]["cc_p0.7"],
        "best_cand(候选池上限)": lambda r: r["e3"]["err"]["best_cand"],
        "oracle{chosen,unet}": lambda r: best(r["e6"]["err"]["chosen"], r["e6"]["err"]["unet"]),
        "oracle{chosen,unet,partition}": lambda r: best(r["e6"]["err"]["chosen"], r["e6"]["err"]["unet"], r["e3"]["err"]["partition"]),
        "oracle{+best_cand}": lambda r: best(r["e6"]["err"]["chosen"], r["e6"]["err"]["unet"], r["e3"]["err"]["partition"], r["e3"]["err"]["best_cand"]),
    }
    out = {"n": len(rows), "all": {}, "by_verdict": {}}
    print(f"{'method':32s} px_mean median  le20px  blob>=60 blob>=150")
    for m, f in methods.items():
        x = agg(rows, f)
        out["all"][m] = x
        print(f"{m:32s} {x['px_mean']:7.1f} {x['px_median']:6.0f} {x['le20px']:7.1%} {x['blob_ge60']:8.1%} {x['blob_ge150']:8.1%}")
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        out["by_verdict"][v] = {m: agg(rr, f) for m, f in methods.items()}
        print(f"-- {v} n={len(rr)}  (blob>=150) " + "  ".join(f"{m}={out['by_verdict'][v][m]['blob_ge150']:.1%}" for m in ("chosen", "unet", "partition(模板)", "rule_dis_T150", "best_cand(候选池上限)", "oracle{chosen,unet,partition}")))
    # 三法互补：partition 在 chosen 与 unet 都大块错的条目上对不对
    both_bad = [r for r in rows if r["e6"]["err"]["chosen"]["blob"] >= 150 and r["e6"]["err"]["unet"]["blob"] >= 150]
    print(f"chosen 与 unet 都大块错 {len(both_bad)} 条，其中模板归属对的 {sum(1 for r in both_bad if r['e3']['err']['partition']['blob'] < 60)} 条")
    jdump(out, OUT_ROOT / "exp6" / "join_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
