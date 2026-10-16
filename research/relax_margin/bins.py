# -*- coding: utf-8 -*-
"""读 `pool.py` 的 jsonl，按库 top1 置信度（cov）× 领先第二名（gap）分档，出人裁一致率、
整理本一致率与 95% 单侧上界（Clopper-Pearson）。

    python research/relax_margin/bins.py pool_vol0*.jsonl [--md]

「可放行」子池（任务书 item 2 的硬约束）：不碰 己／已／巳 一族、不碰形近对表
（`confusable.partners` 手工＋人裁＋字体表、铁证补充表；top1 本身在 `NEVER_MATCH_FAMILIES`
也算），库无护栏，整理本没有明说不同（`align_op != replace`）。
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

COV_EDGES = [0.0, 0.90, 0.94, 0.96, 0.97, 0.98, 0.99, 1.0001]
GAP_EDGES = [0.0, 0.02, 0.05, 0.10, 1.0]


def upper95(k: int, n: int) -> float:
    """单侧 95% Clopper-Pearson 上界。0 错时 = 1 - 0.05^(1/n)。"""
    if n == 0:
        return 1.0
    if k == 0:
        return 1 - 0.05 ** (1 / n)
    if k >= n:
        return 1.0
    from scipy.stats import beta
    return float(beta.ppf(0.95, k + 1, n - k))


def band(x: float, edges: list[float]) -> str:
    for lo, hi in zip(edges, edges[1:]):
        if lo <= x < hi:
            return f"[{lo:.2f},{min(hi, 1):.2f})"
    return "?"


def eligible(r: dict) -> bool:
    return (not r["jys"] and not r["confusable"] and r["guard"] is None
            and r.get("align_op") != "replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--gap", action="store_true", help="按 cov×gap 二维分档")
    ap.add_argument("--min-gap", type=float, default=0.0)
    a = ap.parse_args()
    rows = [json.loads(l) for f in a.files for l in open(f, encoding="utf-8")]

    def key(r):
        k = band(r["c1"], COV_EDGES)
        return (k, band(r["gap"], GAP_EDGES)) if a.gap else (k,)

    agg: dict = defaultdict(lambda: defaultdict(int))
    for r in rows:
        el = eligible(r) and r["gap"] >= a.min_gap
        g = agg[key(r)]
        g["n"] += 1
        g["elig"] += el
        if not el:
            continue
        if r["human_ok"] is not None:
            g["h_n"] += 1
            g["h_bad"] += (not r["human_ok"])
            g["h_form"] += (not r["human_exact"])
        if r["align_char"]:
            g["r_n"] += 1
            g["r_ok"] += r["ref_agree"]
    print("| 档 | 池内格数 | 可放行子池 | 有人裁 | 人裁不一致(义) | 人裁不一致(形) | 义错 95% 上界 | 有整理本对齐 | 整理本一致 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for k in sorted(agg):
        g = agg[k]
        ub = upper95(g["h_bad"], g["h_n"]) if g["h_n"] else None
        print(f"| {' × '.join(k)} | {g['n']} | {g['elig']} | {g['h_n']} | {g['h_bad']} | {g['h_form']} | "
              f"{'—' if ub is None else f'{ub:.2%}'} | {g['r_n']} | {g['r_ok']} |")


if __name__ == "__main__":
    main()
