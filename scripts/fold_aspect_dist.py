# -*- coding: utf-8 -*-
"""fold_aspect 阈值标定：按整理本字（坐标对位）统计「日／曰」字块的宽/高分布（`char_index` 的 width/height）。

    python scripts/fold_aspect_dist.py <产物包根>/<册> [--lo 0.85 --hi 1.0]

产物目录布局 `<册目录>/char_index/pNNNN.json`、`<册目录>/align_ref/pNNNN.json`（取 `coord` 的 ref_char，缺则 `chars[].align_char`）。
输出两类字的分位数，并按 (lo, hi) 数落在「判日／判曰／居中」的格数，用来校准书级 `fold_aspect`。只读。
"""
import argparse
import glob
import json
import os
import statistics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vol_dir")
    ap.add_argument("--lo", type=float, default=0.85)
    ap.add_argument("--hi", type=float, default=1.0)
    a = ap.parse_args()
    got = {"日": [], "曰": []}
    for f in sorted(glob.glob(os.path.join(a.vol_dir, "char_index", "p*.json"))):
        ci = json.load(open(f, encoding="utf-8")).get("char_index") or json.load(open(f, encoding="utf-8"))
        arf = os.path.join(a.vol_dir, "align_ref", os.path.basename(f))
        if not os.path.exists(arf):
            continue
        ar = json.load(open(arf, encoding="utf-8")).get("align_ref") or {}
        ref = {c["id"]: c.get("ref_char") for c in ar.get("coord", [])}
        ref.update({c["id"]: c.get("align_char") for c in ar.get("chars", []) if c.get("align_char")})
        for col in ci.get("columns", []):
            for c in col.get("chars", []):
                ch = ref.get(c["id"])
                if ch in got and c.get("width") and c.get("height") and not c.get("sub"):
                    got[ch].append(c["width"] / c["height"])
    for ch, v in got.items():
        if not v:
            print(ch, "无样本")
            continue
        q = statistics.quantiles(v, n=20)
        print(f"{ch} n={len(v)} 均值 {statistics.fmean(v):.3f} p5 {q[0]:.3f} p25 {q[4]:.3f} 中位 {q[9]:.3f} p75 {q[14]:.3f} p95 {q[18]:.3f}"
              f"  判日(≤{a.lo}) {sum(x <= a.lo for x in v)}  判曰(≥{a.hi}) {sum(x >= a.hi for x in v)}  居中 {sum(a.lo < x < a.hi for x in v)}")


if __name__ == "__main__":
    main()
