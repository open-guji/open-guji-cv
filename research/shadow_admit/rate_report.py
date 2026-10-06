# -*- coding: utf-8 -*-
"""沙箱重跑 seed_admit 的待审率前后对比（D3 道）。

    python rate_report.py vol05=<快照 seed_admit 目录> ...  --runs <runs 根>/<vol>/{base,rare_ref,promote99,both}
待审率 = admit=False 的格 / 全部格（含 excluded、occluded）；`新增放行` 只数 base 里待审、该方案里放行的格。
"""
from __future__ import annotations

import collections
import glob
import json
import sys


def cells(d):
    out = {}
    for f in glob.glob(f"{d}/p*.json"):
        for c in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
            for r in c.get("chars") or []:
                out[r["id"]] = r
    return out


def main():
    runs = sys.argv[sys.argv.index("--runs") + 1]
    snaps = dict(a.split("=", 1) for a in sys.argv[1:sys.argv.index("--runs")])
    print("| 册 | 方案 | 格数 | 待审 | 待审率 | 相对 base | 新增放行 | 新增放行的通道 | 已放行格被改字 |\n|---|---|---|---|---|---|---|---|---|")
    for b, snap in snaps.items():
        S = cells(snap)
        B = cells(f"{runs}/{b}/base")
        rows = [("快照(09-28)", S)] + [(t, cells(f"{runs}/{b}/{t}")) for t in ("base", "rare_ref", "promote99", "both")
                                    if glob.glob(f"{runs}/{b}/{t}/p*.json")]
        for name, C in rows:
            n = len(C)
            pend = sum(not r["admit"] for r in C.values())
            bp = sum(not r["admit"] for r in B.values())
            new = [i for i, r in C.items() if r["admit"] and i in B and not B[i]["admit"]]
            chg = sum(1 for i, r in C.items() if i in B and B[i]["admit"] and r["admit"] and r["char"] != B[i]["char"])
            ch = collections.Counter(C[i]["channel"] for i in new)
            print(f"| {b} | {name} | {n} | {pend} | {pend / n:.2%} | {(pend - bp) / bp:+.1%} | {len(new)} | "
                  f"{dict(ch) if ch else ''} | {chg} |")


if __name__ == "__main__":
    main()
